/*
 * Slab USBIP - Generic DWC2 Device Controller with USBIP Server
 *
 * Emulates the Synopsys DWC2 OTG USB controller in device mode and exports
 * the USB device via the USBIP protocol. The device is generic -- firmware
 * configures USB class (CDC, HID, etc.) at runtime via DWC2 registers.
 *
 * Architecture:
 *   Firmware writes DWC2 registers (0x50000000)
 *       |
 *       v
 *   [slab-usbip device]  -- DWC2 register emulation + USBIP TCP server
 *       |
 *       v (TCP, USBIP v1.1.1)
 *   [Host: usbip attach / Python usbip_client.py]
 *
 * Data flow (host -> firmware):
 *   1. USBIP client sends CMD_SUBMIT (SETUP/OUT data)
 *   2. This device injects data into DWC2 RX FIFO + status queue
 *   3. IRQ fires, firmware reads GRXSTSP + FIFO data
 *
 * Data flow (firmware -> host):
 *   1. Firmware writes TX FIFO (e.g., 0x50001000 for EP0)
 *   2. This device captures bytes, tracks DIEPTSIZ transfer length
 *   3. On transfer complete (XFRC), sends USBIP RET_SUBMIT with TX data
 *
 * Reference: Python usb_cdc_peripheral.py, slab_backends/usbip.py
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2026 Twisted Wires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include "qemu/osdep.h"
#include "qapi/error.h"
#include "qemu/error-report.h"
#include "hw/core/sysbus.h"
#include "hw/core/qdev-properties.h"
#include "hw/core/irq.h"
#include "qom/object.h"
#include "qemu/main-loop.h"
#include "qemu/sockets.h"

#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <fcntl.h>
#include <errno.h>

/* ========================================================================= */
/*                          DWC2 REGISTER OFFSETS                            */
/* ========================================================================= */

/* Core global registers */
#define DWC2_GOTGCTL    0x000
#define DWC2_GOTGINT    0x004
#define DWC2_GAHBCFG    0x008
#define DWC2_GUSBCFG    0x00C
#define DWC2_GRSTCTL    0x010
#define DWC2_GINTSTS    0x014
#define DWC2_GINTMSK    0x018
#define DWC2_GRXSTSR    0x01C
#define DWC2_GRXSTSP    0x020
#define DWC2_GRXFSIZ    0x024
#define DWC2_DIEPTXF0   0x028

/* Device-mode registers */
#define DWC2_DCFG       0x800
#define DWC2_DCTL       0x804
#define DWC2_DSTS       0x808
#define DWC2_DIEPMSK    0x810
#define DWC2_DOEPMSK    0x814
#define DWC2_DAINT      0x818
#define DWC2_DAINTMSK   0x81C

/* IN endpoint registers (stride 0x20) */
#define DWC2_DIEPCTL(n)  (0x900 + (n) * 0x20)
#define DWC2_DIEPINT(n)  (0x908 + (n) * 0x20)
#define DWC2_DIEPTSIZ(n) (0x910 + (n) * 0x20)
#define DWC2_DTXFSTS(n)  (0x918 + (n) * 0x20)

/* OUT endpoint registers (stride 0x20) */
#define DWC2_DOEPCTL(n)  (0xB00 + (n) * 0x20)
#define DWC2_DOEPINT(n)  (0xB08 + (n) * 0x20)
#define DWC2_DOEPTSIZ(n) (0xB10 + (n) * 0x20)

/* FIFOs: EP0 at 0x1000, EP1 at 0x2000, etc. */
#define DWC2_FIFO(n)     (0x1000 + (n) * 0x1000)

/* GINTSTS bits */
#define GINTSTS_RXFLVL   (1 << 4)
#define GINTSTS_USBRST   (1 << 12)
#define GINTSTS_ENUMDNE  (1 << 13)
#define GINTSTS_IEPINT   (1 << 18)
#define GINTSTS_OEPINT   (1 << 19)

/* DWC2 RX status packet status codes */
#define PKTSTS_DATA_UPDT   0x2
#define PKTSTS_XFER_COMP   0x3
#define PKTSTS_SETUP_COMP  0x4
#define PKTSTS_SETUP_UPDT  0x6

/* ========================================================================= */
/*                          USBIP PROTOCOL CONSTANTS                         */
/* ========================================================================= */

#define USBIP_VERSION       0x0111

#define OP_REQ_DEVLIST      0x8005
#define OP_REP_DEVLIST      0x0005
#define OP_REQ_IMPORT       0x8003
#define OP_REP_IMPORT       0x0003
#define USBIP_CMD_SUBMIT    0x0001
#define USBIP_RET_SUBMIT    0x0003
#define USBIP_CMD_UNLINK    0x0002
#define USBIP_RET_UNLINK    0x0004

/* USBIP device info */
#define USBIP_DEV_PATH_LEN  256
#define USBIP_BUSID_LEN     32

/* USB speeds */
#define USB_SPEED_FULL       2

/* ========================================================================= */
/*                          DEVICE STATE                                     */
/* ========================================================================= */

#define TYPE_SLAB_USBIP "slab-usbip"
OBJECT_DECLARE_SIMPLE_TYPE(SlabUSBIPState, SLAB_USBIP)

#define MAX_EPS      4
#define RX_STATUS_SIZE 64
#define RX_FIFO_SIZE   8192
#define TX_FIFO_SIZE   4096
#define REG_SPACE_SIZE 0x10000

/* RX status queue entry */
typedef struct {
    uint8_t epnum;
    uint8_t pktsts;
    uint16_t bcnt;
} RxStatusEntry;

/* Pending URB (waiting for firmware TX response) */
typedef struct {
    uint32_t seqnum;
    uint32_t devid;
    uint32_t direction;
    uint32_t endpoint;
    uint32_t transfer_buffer_length;
    bool active;
} PendingURB;

struct SlabUSBIPState {
    /*< private >*/
    SysBusDevice parent_obj;

    /*< public >*/
    MemoryRegion iomem;

    /* DWC2 registers */
    uint32_t regs[REG_SPACE_SIZE / 4];

    /* RX status queue (circular) */
    RxStatusEntry rx_status[RX_STATUS_SIZE];
    int rx_status_head;
    int rx_status_count;

    /* RX data FIFO (shared, circular) */
    uint8_t rx_fifo[RX_FIFO_SIZE];
    int rx_fifo_head;
    int rx_fifo_count;

    /* TX FIFO per endpoint */
    uint8_t tx_fifo[MAX_EPS][TX_FIFO_SIZE];
    int tx_fifo_len[MAX_EPS];
    int tx_pending[MAX_EPS];    /* bytes remaining in current IN xfer */

    /* USBIP server */
    int32_t usbip_port;
    int listen_fd;
    int client_fd;
    bool client_attached;

    /* Pending URBs per endpoint */
    PendingURB pending_urb[MAX_EPS];

    /* USBIP receive buffer (for incremental parsing) */
    uint8_t recv_buf[512];
    int recv_len;
    int recv_expected;
    int recv_state;             /* 0=header, 1=body, 2=data */

    /* USB device state (from firmware DCFG/DCTL) */
    bool connected;
    uint8_t dev_address;

    /* IRQ output */
    qemu_irq irq;
};

/* ========================================================================= */
/*                          DWC2 HELPER FUNCTIONS                            */
/* ========================================================================= */

static inline uint32_t dwc2_reg_read(SlabUSBIPState *s, uint32_t offset)
{
    if (offset < REG_SPACE_SIZE) {
        return s->regs[offset / 4];
    }
    return 0;
}

static inline void dwc2_reg_write(SlabUSBIPState *s, uint32_t offset,
                                   uint32_t value)
{
    if (offset < REG_SPACE_SIZE) {
        s->regs[offset / 4] = value;
    }
}

/* Push entry to RX status queue */
static void rx_status_push(SlabUSBIPState *s, uint8_t epnum, uint8_t pktsts,
                           uint16_t bcnt)
{
    int idx;

    if (s->rx_status_count >= RX_STATUS_SIZE) {
        warn_report("slab-usbip: RX status queue full");
        return;
    }
    idx = (s->rx_status_head + s->rx_status_count) % RX_STATUS_SIZE;
    s->rx_status[idx].epnum = epnum;
    s->rx_status[idx].pktsts = pktsts;
    s->rx_status[idx].bcnt = bcnt;
    s->rx_status_count++;
}

/* Peek front of RX status queue */
static bool rx_status_peek(SlabUSBIPState *s, RxStatusEntry *out)
{
    if (s->rx_status_count == 0) {
        return false;
    }
    *out = s->rx_status[s->rx_status_head];
    return true;
}

/* Pop front of RX status queue */
static bool rx_status_pop(SlabUSBIPState *s, RxStatusEntry *out)
{
    if (s->rx_status_count == 0) {
        return false;
    }
    *out = s->rx_status[s->rx_status_head];
    s->rx_status_head = (s->rx_status_head + 1) % RX_STATUS_SIZE;
    s->rx_status_count--;
    return true;
}

/* Push data to RX FIFO */
static void rx_fifo_push(SlabUSBIPState *s, const uint8_t *data, int len)
{
    int i, idx;

    for (i = 0; i < len; i++) {
        if (s->rx_fifo_count >= RX_FIFO_SIZE) {
            warn_report("slab-usbip: RX FIFO full");
            return;
        }
        idx = (s->rx_fifo_head + s->rx_fifo_count) % RX_FIFO_SIZE;
        s->rx_fifo[idx] = data[i];
        s->rx_fifo_count++;
    }
}

/* Pop up to 4 bytes from RX FIFO as a 32-bit word */
static uint32_t rx_fifo_pop_word(SlabUSBIPState *s)
{
    uint32_t word = 0;
    int i, n;

    n = MIN(4, s->rx_fifo_count);
    for (i = 0; i < n; i++) {
        word |= (uint32_t)s->rx_fifo[s->rx_fifo_head] << (i * 8);
        s->rx_fifo_head = (s->rx_fifo_head + 1) % RX_FIFO_SIZE;
        s->rx_fifo_count--;
    }
    return word;
}

/* Flush all FIFOs and queues */
static void dwc2_flush_all(SlabUSBIPState *s)
{
    int i;

    s->rx_status_head = 0;
    s->rx_status_count = 0;
    s->rx_fifo_head = 0;
    s->rx_fifo_count = 0;
    for (i = 0; i < MAX_EPS; i++) {
        s->tx_fifo_len[i] = 0;
        s->tx_pending[i] = 0;
    }
}

/* ========================================================================= */
/*                          IRQ MANAGEMENT                                   */
/* ========================================================================= */

/* Compute dynamic GINTSTS (RXFLVL, IEPINT, OEPINT) */
static uint32_t dwc2_compute_gintsts(SlabUSBIPState *s)
{
    uint32_t value = dwc2_reg_read(s, DWC2_GINTSTS);
    uint32_t daintmsk = dwc2_reg_read(s, DWC2_DAINTMSK);
    uint32_t diepmsk = dwc2_reg_read(s, DWC2_DIEPMSK);
    uint32_t doepmsk = dwc2_reg_read(s, DWC2_DOEPMSK);
    bool iep_pending = false, oep_pending = false;
    int ep;

    /* RXFLVL (bit 4) */
    if (s->rx_status_count > 0) {
        value |= GINTSTS_RXFLVL;
    } else {
        value &= ~GINTSTS_RXFLVL;
    }

    /* IEPINT/OEPINT from DAINT chain */
    for (ep = 0; ep < MAX_EPS; ep++) {
        if ((dwc2_reg_read(s, DWC2_DIEPINT(ep)) & diepmsk) &&
            (daintmsk & (1 << ep))) {
            iep_pending = true;
        }
        if ((dwc2_reg_read(s, DWC2_DOEPINT(ep)) & doepmsk) &&
            (daintmsk & (1 << (16 + ep)))) {
            oep_pending = true;
        }
    }

    if (iep_pending) {
        value |= GINTSTS_IEPINT;
    } else {
        value &= ~GINTSTS_IEPINT;
    }

    if (oep_pending) {
        value |= GINTSTS_OEPINT;
    } else {
        value &= ~GINTSTS_OEPINT;
    }

    return value;
}

/* Compute dynamic DAINT */
static uint32_t dwc2_compute_daint(SlabUSBIPState *s)
{
    uint32_t daint = 0;
    uint32_t diepmsk = dwc2_reg_read(s, DWC2_DIEPMSK);
    uint32_t doepmsk = dwc2_reg_read(s, DWC2_DOEPMSK);
    int ep;

    for (ep = 0; ep < MAX_EPS; ep++) {
        if (dwc2_reg_read(s, DWC2_DIEPINT(ep)) & diepmsk) {
            daint |= (1 << ep);
        }
        if (dwc2_reg_read(s, DWC2_DOEPINT(ep)) & doepmsk) {
            daint |= (1 << (16 + ep));
        }
    }
    return daint;
}

/* Update IRQ line: level = (GINTSTS & GINTMSK) != 0 && GAHBCFG.GINTMSK */
static void dwc2_update_irq(SlabUSBIPState *s)
{
    uint32_t gahbcfg = dwc2_reg_read(s, DWC2_GAHBCFG);
    uint32_t gintsts = dwc2_compute_gintsts(s);
    uint32_t gintmsk = dwc2_reg_read(s, DWC2_GINTMSK);
    int level;

    if (!(gahbcfg & 1)) {
        qemu_set_irq(s->irq, 0);
        return;
    }

    level = (gintsts & gintmsk) ? 1 : 0;
    qemu_set_irq(s->irq, level);
}

/* ========================================================================= */
/*                     USBIP PROTOCOL HELPERS                                */
/* ========================================================================= */

/* Forward declarations */
static void slab_usbip_send_ret_submit(SlabUSBIPState *s, int ep);

static void usbip_send_all(SlabUSBIPState *s, const void *buf, int len)
{
    const uint8_t *p = buf;
    int remaining = len;

    if (s->client_fd < 0) {
        return;
    }

    while (remaining > 0) {
        ssize_t n = send(s->client_fd, p, remaining, MSG_NOSIGNAL);
        if (n <= 0) {
            close(s->client_fd);
            qemu_set_fd_handler(s->client_fd, NULL, NULL, NULL);
            s->client_fd = -1;
            s->client_attached = false;
            return;
        }
        p += n;
        remaining -= n;
    }
}

static int usbip_recv_all(int fd, void *buf, int len)
{
    uint8_t *p = buf;
    int remaining = len;

    while (remaining > 0) {
        ssize_t n = recv(fd, p, remaining, MSG_WAITALL);
        if (n <= 0) {
            return -1;
        }
        p += n;
        remaining -= n;
    }
    return len;
}

/* Build and send USBIP device info block (used by devlist and import) */
static void usbip_send_device_info(SlabUSBIPState *s)
{
    uint8_t buf[312];  /* path(256) + busid(32) + info(24) */

    memset(buf, 0, sizeof(buf));

    /* Device path (256 bytes) */
    snprintf((char *)buf, 256, "/virtual/usb/0");

    /* Bus ID (32 bytes) */
    snprintf((char *)buf + 256, 32, "1-1");

    /* Device info (24 bytes, big-endian) */
    uint8_t *p = buf + 288;
    /* busnum(4) */
    p[0] = 0; p[1] = 0; p[2] = 0; p[3] = 1;
    /* devnum(4) */
    p[4] = 0; p[5] = 0; p[6] = 0; p[7] = 1;
    /* speed(4) = USB_SPEED_FULL */
    p[8] = 0; p[9] = 0; p[10] = 0; p[11] = USB_SPEED_FULL;
    /* idVendor(2) = 0x0483 (STM) */
    p[12] = 0x04; p[13] = 0x83;
    /* idProduct(2) = 0x5740 (VCP) */
    p[14] = 0x57; p[15] = 0x40;
    /* bcdDevice(2) */
    p[16] = 0x02; p[17] = 0x00;
    /* bDeviceClass(1) */
    p[18] = 0x02;  /* CDC */
    /* bDeviceSubClass(1) */
    p[19] = 0x02;
    /* bDeviceProtocol(1) */
    p[20] = 0x00;
    /* bConfigurationValue(1) */
    p[21] = 0x01;
    /* bNumConfigurations(1) */
    p[22] = 0x01;
    /* bNumInterfaces(1) */
    p[23] = 0x02;

    usbip_send_all(s, buf, sizeof(buf));
}

static void usbip_handle_devlist(SlabUSBIPState *s)
{
    uint8_t resp[12];

    /* Response header: version(2) + opcode(2) + status(4) + ndev(4) */
    resp[0] = (USBIP_VERSION >> 8) & 0xFF;
    resp[1] = USBIP_VERSION & 0xFF;
    resp[2] = (OP_REP_DEVLIST >> 8) & 0xFF;
    resp[3] = OP_REP_DEVLIST & 0xFF;
    memset(resp + 4, 0, 4);  /* status = 0 */
    resp[8] = 0; resp[9] = 0; resp[10] = 0; resp[11] = 1;  /* ndev = 1 */

    usbip_send_all(s, resp, 12);
    usbip_send_device_info(s);

    /* Interface info (4 bytes per interface: class, subclass, protocol, pad) */
    uint8_t iface[4] = { 0x02, 0x02, 0x00, 0x00 };  /* CDC class */
    usbip_send_all(s, iface, 4);
    uint8_t iface2[4] = { 0x0A, 0x00, 0x00, 0x00 };  /* CDC Data */
    usbip_send_all(s, iface2, 4);
}

static void usbip_handle_import(SlabUSBIPState *s, const uint8_t *busid)
{
    uint8_t resp[8];

    info_report("slab-usbip: USBIP import request for '%.*s'", 32, busid);

    /* Response header */
    resp[0] = (USBIP_VERSION >> 8) & 0xFF;
    resp[1] = USBIP_VERSION & 0xFF;
    resp[2] = (OP_REP_IMPORT >> 8) & 0xFF;
    resp[3] = OP_REP_IMPORT & 0xFF;
    memset(resp + 4, 0, 4);  /* status = 0 (success) */

    usbip_send_all(s, resp, 8);
    usbip_send_device_info(s);

    s->client_attached = true;
    info_report("slab-usbip: Client attached");

    /* Simulate USB bus reset (host detects device connection) */
    dwc2_reg_write(s, DWC2_GINTSTS,
                   dwc2_reg_read(s, DWC2_GINTSTS) | GINTSTS_USBRST);
    dwc2_update_irq(s);
}

/* Inject a SETUP packet into DWC2 RX path */
static void dwc2_inject_setup(SlabUSBIPState *s, const uint8_t *setup_data)
{
    /* Phase 1: SETUP_UPDT (pktsts=6, bcnt=8, epnum=0) */
    rx_fifo_push(s, setup_data, 8);
    rx_status_push(s, 0, PKTSTS_SETUP_UPDT, 8);

    /* Phase 2: SETUP_COMP (pktsts=4, bcnt=0, epnum=0) */
    rx_status_push(s, 0, PKTSTS_SETUP_COMP, 0);

    dwc2_update_irq(s);
}

/* Inject OUT data into DWC2 RX path for an endpoint */
static void dwc2_inject_out_data(SlabUSBIPState *s, int ep,
                                  const uint8_t *data, int len)
{
    /* DATA_UPDT (pktsts=2) */
    rx_fifo_push(s, data, len);
    rx_status_push(s, ep, PKTSTS_DATA_UPDT, len);

    /* XFER_COMP (pktsts=3) */
    rx_status_push(s, ep, PKTSTS_XFER_COMP, 0);

    /* Set DOEPINT.XFRC (bit 0) */
    dwc2_reg_write(s, DWC2_DOEPINT(ep),
                   dwc2_reg_read(s, DWC2_DOEPINT(ep)) | 0x01);

    dwc2_update_irq(s);
}

static void usbip_handle_submit(SlabUSBIPState *s, const uint8_t *header)
{
    uint32_t seqnum, devid, direction, endpoint;
    uint32_t transfer_flags, transfer_buffer_length;
    uint8_t setup[8];
    uint8_t *transfer_buf = NULL;
    int ep;

    /* Parse 48-byte URB header (big-endian) */
    /* Bytes 0-3: command (already consumed) */
    seqnum = (header[4] << 24) | (header[5] << 16) |
             (header[6] << 8)  | header[7];
    devid = (header[8] << 24) | (header[9] << 16) |
            (header[10] << 8) | header[11];
    direction = (header[12] << 24) | (header[13] << 16) |
                (header[14] << 8)  | header[15];
    endpoint = (header[16] << 24) | (header[17] << 16) |
               (header[18] << 8)  | header[19];
    transfer_flags = (header[20] << 24) | (header[21] << 16) |
                     (header[22] << 8)  | header[23];
    transfer_buffer_length = (header[24] << 24) | (header[25] << 16) |
                              (header[26] << 8)  | header[27];
    /* setup packet at offset 40 (8 bytes, little-endian) */
    memcpy(setup, header + 40, 8);

    (void)transfer_flags;

    info_report("slab-usbip: CMD_SUBMIT seq=%u ep=%u dir=%u len=%u "
                "setup=[%02X %02X %02X%02X %02X%02X %02X%02X]",
                seqnum, endpoint, direction, transfer_buffer_length,
                setup[0], setup[1], setup[2], setup[3],
                setup[4], setup[5], setup[6], setup[7]);

    ep = endpoint & 0x0F;
    if (ep >= MAX_EPS) {
        ep = 0;
    }

    /* Read transfer buffer for OUT direction */
    if (direction == 0 && transfer_buffer_length > 0) {
        transfer_buf = g_malloc(transfer_buffer_length);
        if (usbip_recv_all(s->client_fd, transfer_buf,
                           transfer_buffer_length) < 0) {
            g_free(transfer_buf);
            return;
        }
    }

    /* Store pending URB */
    s->pending_urb[ep].seqnum = seqnum;
    s->pending_urb[ep].devid = devid;
    s->pending_urb[ep].direction = direction;
    s->pending_urb[ep].endpoint = endpoint;
    s->pending_urb[ep].transfer_buffer_length = transfer_buffer_length;
    s->pending_urb[ep].active = true;

    if (ep == 0) {
        /* Control transfer: inject SETUP packet into DWC2 */
        dwc2_inject_setup(s, setup);

        /* If OUT with data, also inject the data after SETUP */
        if (direction == 0 && transfer_buffer_length > 0 && transfer_buf) {
            dwc2_inject_out_data(s, 0, transfer_buf, transfer_buffer_length);
        }

        /* For IN control transfers, firmware will write response to EP0 TX FIFO.
         * The response is sent when firmware completes the transfer (XFRC). */
        if (direction == 0 && transfer_buffer_length == 0) {
            /* Zero-length OUT (status stage) - respond immediately */
            s->pending_urb[ep].active = false;
            slab_usbip_send_ret_submit(s, ep);
        }
    } else {
        /* Bulk/Interrupt endpoint */
        if (direction == 0) {
            /* OUT: host sends data to device */
            if (transfer_buf && transfer_buffer_length > 0) {
                dwc2_inject_out_data(s, ep, transfer_buf,
                                     transfer_buffer_length);
            }
            /* Respond immediately for OUT */
            s->pending_urb[ep].active = false;

            uint8_t resp[48];
            memset(resp, 0, sizeof(resp));
            /* RET_SUBMIT */
            resp[0] = 0; resp[1] = 0; resp[2] = 0; resp[3] = USBIP_RET_SUBMIT;
            resp[4] = (seqnum >> 24) & 0xFF;
            resp[5] = (seqnum >> 16) & 0xFF;
            resp[6] = (seqnum >> 8) & 0xFF;
            resp[7] = seqnum & 0xFF;
            /* devid */
            resp[8] = (devid >> 24) & 0xFF;
            resp[9] = (devid >> 16) & 0xFF;
            resp[10] = (devid >> 8) & 0xFF;
            resp[11] = devid & 0xFF;
            /* actual_length at offset 24 */
            resp[24] = (transfer_buffer_length >> 24) & 0xFF;
            resp[25] = (transfer_buffer_length >> 16) & 0xFF;
            resp[26] = (transfer_buffer_length >> 8) & 0xFF;
            resp[27] = transfer_buffer_length & 0xFF;

            usbip_send_all(s, resp, 48);
        }
        /* For IN: firmware will write data to TX FIFO, sent on XFRC */
    }

    g_free(transfer_buf);
}

static void usbip_handle_unlink(SlabUSBIPState *s, const uint8_t *header)
{
    uint32_t seqnum;
    uint8_t resp[48];

    seqnum = (header[4] << 24) | (header[5] << 16) |
             (header[6] << 8)  | header[7];

    memset(resp, 0, sizeof(resp));
    resp[0] = 0; resp[1] = 0; resp[2] = 0; resp[3] = USBIP_RET_UNLINK;
    resp[4] = (seqnum >> 24) & 0xFF;
    resp[5] = (seqnum >> 16) & 0xFF;
    resp[6] = (seqnum >> 8) & 0xFF;
    resp[7] = seqnum & 0xFF;

    usbip_send_all(s, resp, 48);
}

/* Send USBIP RET_SUBMIT for a completed transfer */
static void slab_usbip_send_ret_submit(SlabUSBIPState *s, int ep)
{
    PendingURB *urb = &s->pending_urb[ep];
    uint8_t resp[48];
    uint32_t actual_length;

    if (!urb->active && ep != 0) {
        /* No pending URB for this endpoint -- might be a firmware-initiated
         * transfer that doesn't correspond to a USBIP request */
        return;
    }

    actual_length = s->tx_fifo_len[ep];

    memset(resp, 0, sizeof(resp));
    /* Command: RET_SUBMIT */
    resp[0] = 0; resp[1] = 0; resp[2] = 0; resp[3] = USBIP_RET_SUBMIT;
    /* seqnum */
    resp[4] = (urb->seqnum >> 24) & 0xFF;
    resp[5] = (urb->seqnum >> 16) & 0xFF;
    resp[6] = (urb->seqnum >> 8) & 0xFF;
    resp[7] = urb->seqnum & 0xFF;
    /* devid */
    resp[8] = (urb->devid >> 24) & 0xFF;
    resp[9] = (urb->devid >> 16) & 0xFF;
    resp[10] = (urb->devid >> 8) & 0xFF;
    resp[11] = urb->devid & 0xFF;
    /* actual_length at offset 24 */
    resp[24] = (actual_length >> 24) & 0xFF;
    resp[25] = (actual_length >> 16) & 0xFF;
    resp[26] = (actual_length >> 8) & 0xFF;
    resp[27] = actual_length & 0xFF;

    usbip_send_all(s, resp, 48);

    /* Send TX FIFO data if IN transfer */
    if (actual_length > 0) {
        usbip_send_all(s, s->tx_fifo[ep], actual_length);
    }

    /* Clear TX FIFO and pending URB */
    s->tx_fifo_len[ep] = 0;
    urb->active = false;
}

/* ========================================================================= */
/*                          USBIP TCP SERVER                                 */
/* ========================================================================= */

static void slab_usbip_client_read(void *opaque)
{
    SlabUSBIPState *s = SLAB_USBIP(opaque);
    uint8_t header[48];
    ssize_t n;
    uint16_t command;

    if (!s->client_attached) {
        /* Pre-attachment: read 8-byte command header */
        uint8_t cmd_hdr[8];
        n = recv(s->client_fd, cmd_hdr, 8, MSG_WAITALL);
        if (n != 8) {
            goto disconnect;
        }

        command = (cmd_hdr[2] << 8) | cmd_hdr[3];

        if (command == OP_REQ_DEVLIST) {
            usbip_handle_devlist(s);
        } else if (command == OP_REQ_IMPORT) {
            /* Read 32-byte busid */
            uint8_t busid[32];
            if (usbip_recv_all(s->client_fd, busid, 32) < 0) {
                goto disconnect;
            }
            usbip_handle_import(s, busid);
        } else {
            warn_report("slab-usbip: Unknown pre-attach command: 0x%04X",
                        command);
        }
        return;
    }

    /* Post-attachment: read 48-byte URB header */
    n = recv(s->client_fd, header, 48, MSG_WAITALL);
    if (n != 48) {
        goto disconnect;
    }

    command = (header[2] << 8) | header[3];

    if (command == OP_REQ_DEVLIST) {
        /* Client can still request devlist after import */
        usbip_handle_devlist(s);
    } else {
        /* Full 48-byte command */
        uint32_t cmd_word = (header[0] << 24) | (header[1] << 16) |
                            (header[2] << 8)  | header[3];

        if (cmd_word == USBIP_CMD_SUBMIT) {
            usbip_handle_submit(s, header);
        } else if (cmd_word == USBIP_CMD_UNLINK) {
            usbip_handle_unlink(s, header);
        } else {
            warn_report("slab-usbip: Unknown command: 0x%08X", cmd_word);
        }
    }
    return;

disconnect:
    info_report("slab-usbip: Client disconnected");
    qemu_set_fd_handler(s->client_fd, NULL, NULL, NULL);
    close(s->client_fd);
    s->client_fd = -1;
    s->client_attached = false;
}

static void slab_usbip_accept(void *opaque)
{
    SlabUSBIPState *s = SLAB_USBIP(opaque);
    struct sockaddr_in addr;
    socklen_t addrlen = sizeof(addr);
    int fd;
    int opt = 1;

    fd = accept(s->listen_fd, (struct sockaddr *)&addr, &addrlen);
    if (fd < 0) {
        return;
    }

    /* Close existing client if any */
    if (s->client_fd >= 0) {
        qemu_set_fd_handler(s->client_fd, NULL, NULL, NULL);
        close(s->client_fd);
    }

    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &opt, sizeof(opt));

    s->client_fd = fd;
    s->client_attached = false;
    s->recv_len = 0;

    info_report("slab-usbip: Client connected from %s:%d",
                inet_ntoa(addr.sin_addr), ntohs(addr.sin_port));

    qemu_set_fd_handler(fd, slab_usbip_client_read, NULL, s);
}

static void slab_usbip_start_server(SlabUSBIPState *s)
{
    struct sockaddr_in addr;
    int fd;
    int opt = 1;

    if (s->usbip_port <= 0) {
        return;
    }

    fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        warn_report("slab-usbip: Failed to create socket: %s",
                     strerror(errno));
        return;
    }

    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(s->usbip_port);
    addr.sin_addr.s_addr = htonl(INADDR_ANY);

    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        warn_report("slab-usbip: Failed to bind port %d: %s",
                     s->usbip_port, strerror(errno));
        close(fd);
        return;
    }

    if (listen(fd, 1) < 0) {
        warn_report("slab-usbip: Failed to listen: %s", strerror(errno));
        close(fd);
        return;
    }

    s->listen_fd = fd;

    /* Register non-blocking accept handler */
    qemu_set_fd_handler(fd, slab_usbip_accept, NULL, s);

    info_report("slab-usbip: USBIP server listening on port %d", s->usbip_port);
    info_report("slab-usbip: To attach: usbip attach -r localhost -b 1-1");
}

/* ========================================================================= */
/*                      DWC2 REGISTER READ/WRITE                             */
/* ========================================================================= */

/* Uncomment for register-level tracing */
#define SLAB_USBIP_TRACE 1

static uint64_t slab_usbip_read(void *opaque, hwaddr offset, unsigned size)
{
    SlabUSBIPState *s = SLAB_USBIP(opaque);
    uint32_t value = 0;

    /* FIFO reads: pop from RX data FIFO */
    if (offset >= 0x1000 && offset < 0x20000) {
        value = rx_fifo_pop_word(s);
#ifdef SLAB_USBIP_TRACE
        info_report("slab-usbip: FIFO READ  [0x%04lx] => 0x%08X (rxcnt=%d)",
                    (unsigned long)offset, value, s->rx_fifo_count);
#endif
        return value;
    }

    switch (offset) {
    case DWC2_GINTSTS:
        value = dwc2_compute_gintsts(s);
        break;

    case DWC2_DAINT:
        value = dwc2_compute_daint(s);
        break;

    case DWC2_GRXSTSR:
        /* Peek status queue (don't pop) */
        {
            RxStatusEntry entry;
            if (rx_status_peek(s, &entry)) {
                value = ((uint32_t)entry.pktsts << 17) |
                        ((uint32_t)entry.bcnt << 4) |
                        entry.epnum;
            }
        }
        break;

    case DWC2_GRXSTSP:
        /* Pop status queue */
        {
            RxStatusEntry entry;
            if (rx_status_pop(s, &entry)) {
                value = ((uint32_t)entry.pktsts << 17) |
                        ((uint32_t)entry.bcnt << 4) |
                        entry.epnum;
                /* SETUP_COMP sets DOEPINT0.STUP (bit 3) */
                if (entry.pktsts == PKTSTS_SETUP_COMP && entry.epnum == 0) {
                    dwc2_reg_write(s, DWC2_DOEPINT(0),
                                   dwc2_reg_read(s, DWC2_DOEPINT(0)) | 0x08);
                }
                dwc2_update_irq(s);
            }
        }
        break;

    default:
        value = dwc2_reg_read(s, offset);
        break;
    }

#ifdef SLAB_USBIP_TRACE
    info_report("slab-usbip: REG  READ  [0x%04lx] => 0x%08X",
                (unsigned long)offset, value);
#endif
    return value;
}

static void slab_usbip_write(void *opaque, hwaddr offset, uint64_t value,
                              unsigned size)
{
    SlabUSBIPState *s = SLAB_USBIP(opaque);
    int ep;

    /* FIFO writes: accumulate in TX FIFO */
    if (offset >= 0x1000 && offset < 0x20000) {
        ep = (offset - 0x1000) / 0x1000;
        if (ep >= MAX_EPS) {
            ep = 0;
        }

        /* Append bytes to TX FIFO */
        if (s->tx_fifo_len[ep] + 4 <= TX_FIFO_SIZE) {
            int i;
            for (i = 0; i < 4 && s->tx_fifo_len[ep] < TX_FIFO_SIZE; i++) {
                s->tx_fifo[ep][s->tx_fifo_len[ep]++] =
                    (value >> (i * 8)) & 0xFF;
            }
        }

#ifdef SLAB_USBIP_TRACE
        info_report("slab-usbip: FIFO WRITE EP%d val=0x%08X len=%d pending=%d",
                    ep, (uint32_t)value, s->tx_fifo_len[ep], s->tx_pending[ep]);
#endif

        /* Track IN transfer progress */
        if (s->tx_pending[ep] > 0) {
            s->tx_pending[ep] -= 4;
            if (s->tx_pending[ep] <= 0) {
                s->tx_pending[ep] = 0;
                /* XFRC: set DIEPINT.XFRC (bit 0) */
                dwc2_reg_write(s, DWC2_DIEPINT(ep),
                               dwc2_reg_read(s, DWC2_DIEPINT(ep)) | 0x01);
                dwc2_update_irq(s);

                /* If there's a pending USBIP URB, send the response */
                if (s->pending_urb[ep].active) {
                    slab_usbip_send_ret_submit(s, ep);
                }
            }
        }
        return;
    }

    /* W1C registers (DIEPINT / DOEPINT) */
    for (ep = 0; ep < MAX_EPS; ep++) {
        if (offset == (uint32_t)DWC2_DIEPINT(ep)) {
            dwc2_reg_write(s, offset,
                           dwc2_reg_read(s, offset) & ~(uint32_t)value);
            dwc2_update_irq(s);
            return;
        }
        if (offset == (uint32_t)DWC2_DOEPINT(ep)) {
            dwc2_reg_write(s, offset,
                           dwc2_reg_read(s, offset) & ~(uint32_t)value);
            dwc2_update_irq(s);
            return;
        }
    }

    switch (offset) {
    case DWC2_GINTSTS: {
        /* W1C */
        uint32_t old_gintsts = dwc2_reg_read(s, DWC2_GINTSTS);
        dwc2_reg_write(s, DWC2_GINTSTS, old_gintsts & ~(uint32_t)value);

        /* When firmware acknowledges USBRST, fire ENUMDNE automatically.
         * Per RM0090 section 35.17.4: after the host resets the bus,
         * the DWC2 core completes speed enumeration and sets ENUMDNE. */
        if ((value & GINTSTS_USBRST) && (old_gintsts & GINTSTS_USBRST)) {
            dwc2_reg_write(s, DWC2_GINTSTS,
                           dwc2_reg_read(s, DWC2_GINTSTS) | GINTSTS_ENUMDNE);
            /* Set DSTS.ENUMSPD = 3 (Full Speed, internal PHY) */
            dwc2_reg_write(s, DWC2_DSTS, 0x00000006);
            info_report("slab-usbip: USBRST acknowledged, firing ENUMDNE");
        }

        dwc2_update_irq(s);
        break;
    }

    case DWC2_GRSTCTL:
        if (value & 0x01) {
            /* Core soft reset */
            dwc2_flush_all(s);
            dwc2_reg_write(s, DWC2_GRSTCTL, 0x80000000);  /* AHB idle */
        }
        if (value & 0x10) {
            /* RX FIFO flush */
            s->rx_status_head = 0;
            s->rx_status_count = 0;
            s->rx_fifo_head = 0;
            s->rx_fifo_count = 0;
        }
        if (value & 0x20) {
            /* TX FIFO flush */
            for (ep = 0; ep < MAX_EPS; ep++) {
                s->tx_fifo_len[ep] = 0;
            }
        }
        break;

    case DWC2_DCTL:
        dwc2_reg_write(s, offset, value);
        if (value & 0x02) {
            s->connected = false;
        } else {
            if (!s->connected) {
                /* Device just connected -- fire ENUMDNE after reset */
                dwc2_reg_write(s, DWC2_GINTSTS,
                               dwc2_reg_read(s, DWC2_GINTSTS) | GINTSTS_ENUMDNE);
                /* DSTS: enumerated speed = full-speed (0x3 << 1) */
                dwc2_reg_write(s, DWC2_DSTS, 0x00000006);
                dwc2_update_irq(s);
            }
            s->connected = true;
        }
        break;

    case DWC2_DCFG:
        dwc2_reg_write(s, offset, value);
        s->dev_address = (value >> 4) & 0x7F;
        break;

    case DWC2_DIEPCTL(0):
        dwc2_reg_write(s, offset, value);
        if (value & (1 << 31)) {
            /* EP0 IN EPENA: start transfer, wait for FIFO data */
            uint32_t tsiz0 = dwc2_reg_read(s, DWC2_DIEPTSIZ(0));
            int xfer_len0 = tsiz0 & 0x7F;  /* EP0 max 127 bytes */
            s->tx_pending[0] = xfer_len0;
            s->tx_fifo_len[0] = 0;

            if (xfer_len0 == 0) {
                /* Zero-length IN (status stage): complete immediately */
                dwc2_reg_write(s, DWC2_DIEPINT(0),
                               dwc2_reg_read(s, DWC2_DIEPINT(0)) | 0x01);
                dwc2_update_irq(s);
                if (s->pending_urb[0].active) {
                    slab_usbip_send_ret_submit(s, 0);
                }
            }
            /* Non-zero: completed when FIFO data fills tx_pending */
        }
        break;

    case DWC2_DIEPCTL(1):
    case DWC2_DIEPCTL(2):
    case DWC2_DIEPCTL(3):
        ep = (offset - 0x900) / 0x20;
        dwc2_reg_write(s, offset, value);
        if (value & (1 << 31)) {
            /* EPENA: start IN transfer */
            uint32_t tsiz = dwc2_reg_read(s, DWC2_DIEPTSIZ(ep));
            int xfer_len = tsiz & 0x7FFFF;
            s->tx_pending[ep] = xfer_len;
            s->tx_fifo_len[ep] = 0;

            if (xfer_len == 0) {
                /* Zero-length: immediately complete */
                dwc2_reg_write(s, DWC2_DIEPINT(ep),
                               dwc2_reg_read(s, DWC2_DIEPINT(ep)) | 0x01);
                dwc2_update_irq(s);
                if (s->pending_urb[ep].active) {
                    slab_usbip_send_ret_submit(s, ep);
                }
            }
        }
        break;

    case DWC2_DOEPCTL(0):
    case DWC2_DOEPCTL(1):
    case DWC2_DOEPCTL(2):
    case DWC2_DOEPCTL(3):
        dwc2_reg_write(s, offset, value);
        break;

    case DWC2_GINTMSK:
    case DWC2_GAHBCFG:
    case DWC2_DAINTMSK:
    case DWC2_DIEPMSK:
    case DWC2_DOEPMSK:
        dwc2_reg_write(s, offset, value);
        dwc2_update_irq(s);
        break;

    default:
#ifdef SLAB_USBIP_TRACE
        info_report("slab-usbip: REG  WRITE [0x%04lx] <= 0x%08lX",
                    (unsigned long)offset, (unsigned long)value);
#endif
        dwc2_reg_write(s, offset, value);
        break;
    }
}

static const MemoryRegionOps slab_usbip_ops = {
    .read = slab_usbip_read,
    .write = slab_usbip_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .impl = {
        .min_access_size = 4,
        .max_access_size = 4,
    },
};

/* ========================================================================= */
/*                     DEVICE LIFECYCLE                                       */
/* ========================================================================= */

static void slab_usbip_init_regs(SlabUSBIPState *s)
{
    memset(s->regs, 0, sizeof(s->regs));

    /* Default register values (match DWC2 device mode) */
    dwc2_reg_write(s, DWC2_GOTGCTL, 0x00010000);   /* Current mode = device */
    dwc2_reg_write(s, DWC2_GUSBCFG, 0x00001440);   /* Full-speed */
    dwc2_reg_write(s, DWC2_GRSTCTL, 0x80000000);   /* AHB master idle */
    dwc2_reg_write(s, DWC2_GINTSTS, 0x04000020);   /* Session req, mode mismatch */
    dwc2_reg_write(s, DWC2_GRXFSIZ, 0x00000200);   /* 512 bytes */
    dwc2_reg_write(s, DWC2_DIEPTXF0, 0x02000200);
    dwc2_reg_write(s, DWC2_DSTS, 0x00000010);      /* Suspend */

    /* FIFO space available for all EPs */
    int ep;
    for (ep = 0; ep < MAX_EPS; ep++) {
        dwc2_reg_write(s, DWC2_DTXFSTS(ep), 0x00000200);
    }
}

static void slab_usbip_realize(DeviceState *dev, Error **errp)
{
    SlabUSBIPState *s = SLAB_USBIP(dev);

    /* Initialize memory region (256KB for DWC2 OTG) */
    memory_region_init_io(&s->iomem, OBJECT(s), &slab_usbip_ops, s,
                          "slab-usbip", 0x40000);
    sysbus_init_mmio(SYS_BUS_DEVICE(dev), &s->iomem);

    /* Initialize IRQ output */
    sysbus_init_irq(SYS_BUS_DEVICE(dev), &s->irq);

    /* Initialize DWC2 state */
    slab_usbip_init_regs(s);
    dwc2_flush_all(s);

    s->connected = false;
    s->dev_address = 0;
    s->listen_fd = -1;
    s->client_fd = -1;
    s->client_attached = false;
    memset(s->pending_urb, 0, sizeof(s->pending_urb));

    /* Start USBIP TCP server */
    slab_usbip_start_server(s);
}

static void slab_usbip_unrealize(DeviceState *dev)
{
    SlabUSBIPState *s = SLAB_USBIP(dev);

    if (s->client_fd >= 0) {
        qemu_set_fd_handler(s->client_fd, NULL, NULL, NULL);
        close(s->client_fd);
    }
    if (s->listen_fd >= 0) {
        qemu_set_fd_handler(s->listen_fd, NULL, NULL, NULL);
        close(s->listen_fd);
    }
}

static const Property slab_usbip_properties[] = {
    DEFINE_PROP_INT32("usbip-port", SlabUSBIPState, usbip_port, 3240),
};

static void slab_usbip_class_init(ObjectClass *oc, const void *data)
{
    DeviceClass *dc = DEVICE_CLASS(oc);

    dc->realize = slab_usbip_realize;
    dc->unrealize = slab_usbip_unrealize;
    dc->desc = "Slab DWC2 USB Device Controller with USBIP Server";
    device_class_set_props(dc, slab_usbip_properties);
}

static const TypeInfo slab_usbip_info = {
    .name = TYPE_SLAB_USBIP,
    .parent = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(SlabUSBIPState),
    .class_init = slab_usbip_class_init,
};

static void slab_usbip_register_types(void)
{
    type_register_static(&slab_usbip_info);
}

type_init(slab_usbip_register_types)
