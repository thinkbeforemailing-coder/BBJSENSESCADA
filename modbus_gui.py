"""On-site Modbus test GUI -- no internet needed.

Built for commissioning: a device gets physically wired to the
industrial PC at site, and needs to be confirmed talking correctly
*before* it's added to the cloud config and goes live. Two ways to
check that, both against the local serial port only (nothing here
talks to the backend):

  - "Discover new device": don't know the slave ID yet? Scan a range
    of IDs against one test register and see which ones answer.
  - "Manual register read": know the slave ID? Read any register by
    hand -- doesn't need to be in config_cache.json.

Devices already in config_cache.json (already-commissioned, already
live) can also be picked from a list and scanned tag-by-tag, as a
regression check that nothing's drifted -- see the "Devices" panel.

Usage:

    net stop "BBJ Sense Gateway"      (frees the COM port -- see below)
    python modbus_gui.py
    net start "BBJ Sense Gateway"

Like diagnose_modbus.py and modbus_console.py, this needs the serial
port to itself -- the live gateway service holds it while running.
"""

import json
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk

from pymodbus.client import ModbusSerialClient

from diagnose_modbus import (
    decode_registers,
    normalize_parity,
    normalize_stop_bits,
    read_one_register,
)


CONFIG_CACHE_PATH = Path(__file__).parent / "config_cache.json"


class ModbusGuiApp:

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("BBJ Sense -- On-Site Modbus Tester")
        self.root.geometry("880x680")

        self.client: ModbusSerialClient | None = None
        self.devices: list[dict] = []

        self._build_connection_panel()
        self._build_discovery_panel()
        self._build_manual_read_panel()
        self._build_device_panel()
        self._build_log_panel()

        self.load_devices()

    # -- connection ------------------------------------------------

    def _build_connection_panel(self) -> None:
        frame = ttk.LabelFrame(self.root, text="Connection")
        frame.pack(fill="x", padx=10, pady=(10, 5))

        self.port_var = tk.StringVar(value="COM6")
        self.baud_var = tk.StringVar(value="4800")
        self.parity_var = tk.StringVar(value="O")
        self.stopbits_var = tk.StringVar(value="2")
        self.status_var = tk.StringVar(value="Not connected")

        ttk.Label(frame, text="Port").grid(row=0, column=0, padx=5, pady=5)
        ttk.Entry(frame, textvariable=self.port_var, width=8).grid(
            row=0, column=1, padx=5
        )

        ttk.Label(frame, text="Baud").grid(row=0, column=2, padx=5)
        ttk.Entry(frame, textvariable=self.baud_var, width=8).grid(
            row=0, column=3, padx=5
        )

        ttk.Label(frame, text="Parity").grid(row=0, column=4, padx=5)
        ttk.Entry(frame, textvariable=self.parity_var, width=4).grid(
            row=0, column=5, padx=5
        )

        ttk.Label(frame, text="Stop bits").grid(row=0, column=6, padx=5)
        ttk.Entry(frame, textvariable=self.stopbits_var, width=4).grid(
            row=0, column=7, padx=5
        )

        ttk.Button(frame, text="Connect", command=self.connect).grid(
            row=0, column=8, padx=8
        )
        ttk.Button(frame, text="Disconnect", command=self.disconnect).grid(
            row=0, column=9, padx=5
        )
        ttk.Button(frame, text="List Ports", command=self.list_ports).grid(
            row=0, column=10, padx=5
        )

        ttk.Label(frame, textvariable=self.status_var).grid(
            row=0, column=11, padx=10
        )

    def connect(self) -> None:
        if self.client is not None:
            self.disconnect()

        port = self.port_var.get().strip()

        client = ModbusSerialClient(
            port=port,
            baudrate=int(self.baud_var.get()),
            parity=normalize_parity(self.parity_var.get()),
            stopbits=normalize_stop_bits(self.stopbits_var.get()),
            bytesize=8,
            timeout=2,
        )

        if not client.connect():
            self.status_var.set(f"FAILED to open {port}")
            self.log(
                f"FAILED to open {port} -- either another process has "
                "it open (stop the gateway service: "
                'net stop "BBJ Sense Gateway") or it is not a real '
                "port right now. Try List Ports."
            )
            return

        self.client = client
        self.status_var.set(f"Connected: {port}")
        self.log(f"Connected to {port}.")

    def disconnect(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None
            self.log("Disconnected.")
        self.status_var.set("Not connected")

    def list_ports(self) -> None:
        from serial.tools import list_ports as _list_ports

        ports = list(_list_ports.comports())

        if not ports:
            self.log(
                "No COM ports detected by Windows at all -- that's a "
                "driver/USB-adapter problem, not a wiring problem."
            )
            return

        self.log(f"{len(ports)} COM port(s) detected:")
        for port in ports:
            self.log(f"  {port.device}  {port.description}")

    # -- discover a new device's slave ID ----------------------------

    def _build_discovery_panel(self) -> None:
        frame = ttk.LabelFrame(
            self.root,
            text="Discover new device (don't know the slave ID yet?)",
        )
        frame.pack(fill="x", padx=10, pady=5)

        self.scan_from_var = tk.StringVar(value="1")
        self.scan_to_var = tk.StringVar(value="10")
        self.scan_address_var = tk.StringVar(value="0")
        self.scan_count_var = tk.StringVar(value="2")
        self.scan_func_var = tk.StringVar(value="3")

        ttk.Label(frame, text="Slave ID from").grid(
            row=0, column=0, padx=3, pady=5
        )
        ttk.Entry(frame, textvariable=self.scan_from_var, width=5).grid(
            row=0, column=1, padx=3
        )

        ttk.Label(frame, text="to").grid(row=0, column=2, padx=3)
        ttk.Entry(frame, textvariable=self.scan_to_var, width=5).grid(
            row=0, column=3, padx=3
        )

        ttk.Label(frame, text="test register addr").grid(
            row=0, column=4, padx=3
        )
        ttk.Entry(
            frame, textvariable=self.scan_address_var, width=6
        ).grid(row=0, column=5, padx=3)

        ttk.Label(frame, text="count").grid(row=0, column=6, padx=3)
        ttk.Entry(frame, textvariable=self.scan_count_var, width=4).grid(
            row=0, column=7, padx=3
        )

        ttk.Label(frame, text="func code").grid(row=0, column=8, padx=3)
        ttk.Entry(frame, textvariable=self.scan_func_var, width=4).grid(
            row=0, column=9, padx=3
        )

        ttk.Button(
            frame, text="Scan Slave IDs", command=self.scan_slave_ids
        ).grid(row=0, column=10, padx=10)

        ttk.Label(
            frame,
            text=(
                "Any response -- even a Modbus error like 'illegal "
                "address' -- means a device IS there and wired "
                "correctly; only a timeout means nothing answered. "
                "The test register doesn't need to be valid for the "
                "actual meter, it's just something to knock with."
            ),
            wraplength=820,
            foreground="#555555",
        ).grid(row=1, column=0, columnspan=11, padx=5, pady=(0, 5), sticky="w")

    def scan_slave_ids(self) -> None:
        if self.client is None:
            self.log("Connect to a port first.")
            return

        try:
            start = int(self.scan_from_var.get())
            end = int(self.scan_to_var.get())
            address = int(self.scan_address_var.get())
            count = int(self.scan_count_var.get())
            function_code = int(self.scan_func_var.get())
        except ValueError:
            self.log("Slave ID range / register fields must be numbers.")
            return

        self.log(f"Scanning slave IDs {start}-{end} ...")
        self.root.update_idletasks()

        found_any = False

        for slave_id in range(start, end + 1):
            try:
                result = read_one_register(
                    self.client, slave_id, address, count, function_code
                )

                if result.isError():
                    # The device replied -- with a Modbus exception,
                    # but it replied, which is proof it's wired and
                    # listening at this ID. The test register just
                    # isn't valid/readable for it.
                    self.log(
                        f"  slave {slave_id}: ALIVE (responded with "
                        f"a Modbus exception: {result}) -- device is "
                        "present, try a different register"
                    )
                    found_any = True
                else:
                    self.log(
                        f"  slave {slave_id}: ALIVE, raw="
                        f"{list(result.registers)}"
                    )
                    found_any = True

            except Exception:
                # Timeout / no response -- nothing at this ID.
                pass

            self.root.update_idletasks()

        if not found_any:
            self.log(
                f"  No response from any slave ID {start}-{end}. Check "
                "wiring (A/B not swapped, correct COM port), baud/"
                "parity/stop-bit settings, and that the meter is "
                "actually powered."
            )

        self.log("Slave ID scan complete.")

    # -- device list (from config_cache.json) -----------------------

    def _build_device_panel(self) -> None:
        frame = ttk.LabelFrame(
            self.root, text="Devices (from config_cache.json)"
        )
        frame.pack(fill="both", expand=False, padx=10, pady=5)

        left = ttk.Frame(frame)
        left.pack(side="left", fill="y", padx=5, pady=5)

        self.device_listbox = tk.Listbox(left, width=28, height=8)
        self.device_listbox.pack(side="left", fill="y")
        self.device_listbox.bind(
            "<<ListboxSelect>>", self.on_device_select
        )

        right = ttk.Frame(frame)
        right.pack(side="left", fill="both", expand=True, padx=5, pady=5)

        self.device_info_var = tk.StringVar(value="Select a device")
        ttk.Label(right, textvariable=self.device_info_var).pack(
            anchor="w"
        )

        ttk.Button(
            right, text="Scan This Device", command=self.scan_device
        ).pack(anchor="w", pady=5)

        columns = ("tag", "address", "raw", "value", "unit", "status")
        self.results_tree = ttk.Treeview(
            right, columns=columns, show="headings", height=8
        )
        for col, width in zip(
            columns, (150, 70, 150, 90, 60, 200)
        ):
            self.results_tree.heading(col, text=col.title())
            self.results_tree.column(col, width=width)
        self.results_tree.pack(fill="both", expand=True)

    def load_devices(self) -> None:
        self.device_listbox.delete(0, tk.END)
        self.devices = []

        if not CONFIG_CACHE_PATH.exists():
            self.log(
                f"No config_cache.json found at {CONFIG_CACHE_PATH} -- "
                "device list will be empty. Manual reads below still "
                "work without it."
            )
            return

        config = json.loads(CONFIG_CACHE_PATH.read_text())
        self.devices = config.get("devices", [])

        for device in self.devices:
            conn = device.get("connection") or {}
            label = (
                f"{device.get('device_name')} "
                f"(slave {conn.get('slave_id')}, {conn.get('serial_port')})"
            )
            self.device_listbox.insert(tk.END, label)

        self.log(f"Loaded {len(self.devices)} device(s) from config.")

    def on_device_select(self, _event) -> None:
        selection = self.device_listbox.curselection()
        if not selection:
            return

        device = self.devices[selection[0]]
        conn = device.get("connection") or {}

        self.device_info_var.set(
            f"{device.get('device_name')} -- "
            f"{len(device.get('tags', []))} tag(s), "
            f"port={conn.get('serial_port')}, slave={conn.get('slave_id')}"
        )

        # Pre-fill the manual-read panel's slave ID too, since testing
        # one register on the currently-selected device is a common
        # follow-up to a full scan.
        self.slave_id_var.set(str(conn.get("slave_id", "")))

    def scan_device(self) -> None:
        selection = self.device_listbox.curselection()
        if not selection:
            self.log("Select a device first.")
            return

        if self.client is None:
            self.log("Connect to a port first.")
            return

        device = self.devices[selection[0]]
        conn = device.get("connection") or {}
        expected_port = conn.get("serial_port")

        if expected_port and expected_port != self.port_var.get().strip():
            self.log(
                f"Warning: {device.get('device_name')} is configured "
                f"for {expected_port}, but you're connected to "
                f"{self.port_var.get().strip()}. Reconnect to the "
                "right port first."
            )
            return

        for row in self.results_tree.get_children():
            self.results_tree.delete(row)

        slave_id = conn.get("slave_id")
        self.log(f"Scanning {device.get('device_name')} (slave {slave_id})...")

        for tag in device.get("tags", []):
            address = tag.get("register_address")
            count = tag.get("register_count") or 2
            function_code = int(tag.get("function_code") or 3)

            try:
                result = read_one_register(
                    self.client, slave_id, address, count, function_code
                )

                if result.isError():
                    self.results_tree.insert(
                        "", tk.END,
                        values=(
                            tag.get("display_name"), address, "",
                            "", "", f"FAIL: {result}",
                        ),
                    )
                    continue

                registers = list(result.registers)
                value = decode_registers(
                    registers,
                    tag.get("data_type", "float32"),
                    tag.get("byte_order", "big"),
                    tag.get("word_order", "swapped"),
                )
                scaled = (
                    value * float(tag.get("scale", 1.0))
                    + float(tag.get("offset_value", 0.0))
                )

                self.results_tree.insert(
                    "", tk.END,
                    values=(
                        tag.get("display_name"), address, registers,
                        f"{scaled:.3f}", tag.get("unit") or "", "OK",
                    ),
                )

            except Exception as error:
                self.results_tree.insert(
                    "", tk.END,
                    values=(
                        tag.get("display_name"), address, "",
                        "", "", f"ERROR: {error}",
                    ),
                )

        self.log(f"Scan of {device.get('device_name')} complete.")

    # -- manual single-register read ---------------------------------

    def _build_manual_read_panel(self) -> None:
        frame = ttk.LabelFrame(self.root, text="Manual register read")
        frame.pack(fill="x", padx=10, pady=5)

        self.slave_id_var = tk.StringVar(value="1")
        self.address_var = tk.StringVar(value="")
        self.count_var = tk.StringVar(value="2")
        self.func_code_var = tk.StringVar(value="3")
        self.data_type_var = tk.StringVar(value="float32")
        self.byte_order_var = tk.StringVar(value="big")
        self.word_order_var = tk.StringVar(value="swapped")

        fields = [
            ("Slave ID", self.slave_id_var, 5),
            ("Address", self.address_var, 6),
            ("Count", self.count_var, 4),
            ("Func code", self.func_code_var, 4),
            ("Data type", self.data_type_var, 9),
            ("Byte order", self.byte_order_var, 8),
            ("Word order", self.word_order_var, 8),
        ]

        for col, (label, var, width) in enumerate(fields):
            ttk.Label(frame, text=label).grid(
                row=0, column=col * 2, padx=3, pady=5
            )
            ttk.Entry(frame, textvariable=var, width=width).grid(
                row=0, column=col * 2 + 1, padx=3
            )

        ttk.Button(frame, text="Read", command=self.read_single).grid(
            row=0, column=len(fields) * 2, padx=10
        )

    def read_single(self) -> None:
        if self.client is None:
            self.log("Connect to a port first.")
            return

        if not self.address_var.get().strip():
            self.log("Enter a register address.")
            return

        try:
            slave_id = int(self.slave_id_var.get())
            address = int(self.address_var.get())
            count = int(self.count_var.get())
            function_code = int(self.func_code_var.get())

            started = time.monotonic()
            result = read_one_register(
                self.client, slave_id, address, count, function_code
            )
            elapsed_ms = (time.monotonic() - started) * 1000

            if result.isError():
                self.log(
                    f"slave={slave_id} addr={address} FAIL: {result}"
                )
                return

            registers = list(result.registers)
            value = decode_registers(
                registers,
                self.data_type_var.get(),
                self.byte_order_var.get(),
                self.word_order_var.get(),
            )

            self.log(
                f"slave={slave_id} addr={address} raw={registers} "
                f"value={value:.4f} ({elapsed_ms:.0f} ms)"
            )

        except Exception as error:
            self.log(f"ERROR: {error}")

    # -- log -----------------------------------------------------------

    def _build_log_panel(self) -> None:
        frame = ttk.LabelFrame(self.root, text="Log")
        frame.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        self.log_text = tk.Text(frame, height=12, state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=5, pady=5)

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")


def main() -> None:
    root = tk.Tk()
    ModbusGuiApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
