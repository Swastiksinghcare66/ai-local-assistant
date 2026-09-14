from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
from datetime import datetime

import psutil


def _pct(value) -> str:
    return f"{float(value):.0f} percent"


def _gpu_status() -> str | None:

    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            shell=False,
        )

        if result.returncode != 0:
            return None

        line = result.stdout.strip().splitlines()[0]

        parts = [
            x.strip()
            for x in line.split(",")
        ]

        if len(parts) < 4:
            return None

        name, usage, used, total = parts[:4]

        return (
            f"{name} is at {usage} percent GPU utilization. "
            f"Video memory usage is {used} megabytes "
            f"out of {total} megabytes."
        )

    except Exception:
        return None


def answer_local_information(
    text: str,
) -> str | None:

    q = str(
        text or ""
    ).lower().strip()

    now = datetime.now()


    # ------------------------------------------------------------
    # TIME / DATE
    # ------------------------------------------------------------

    wants_time = (
        "time" in q
        and
        not any(
            x in q
            for x in (
                "time complexity",
                "time constant",
                "time domain",
            )
        )
    )

    wants_date = (
        "date" in q
        or "what day" in q
        or "day today" in q
    )


    if wants_time and wants_date:

        return (
            f"It is {now.strftime('%I:%M %p').lstrip('0')} "
            f"on {now.strftime('%A, %B %d, %Y')}."
        )


    if wants_time:

        return (
            f"It is {now.strftime('%I:%M %p').lstrip('0')}."
        )


    if wants_date:

        return (
            f"Today is {now.strftime('%A, %B %d, %Y')}."
        )


    # ------------------------------------------------------------
    # BATTERY
    # ------------------------------------------------------------

    if "battery" in q:

        battery = psutil.sensors_battery()

        if battery is None:
            return (
                "Windows is not exposing battery information "
                "through the current system interface."
            )

        state = (
            "plugged in"
            if battery.power_plugged
            else "running on battery"
        )

        return (
            f"Battery is at {_pct(battery.percent)} "
            f"and the laptop is {state}."
        )


    # ------------------------------------------------------------
    # CPU
    # ------------------------------------------------------------

    if "cpu" in q:

        usage = psutil.cpu_percent(
            interval=0.15
        )

        return (
            f"CPU usage is {_pct(usage)}."
        )


    # ------------------------------------------------------------
    # RAM
    # ------------------------------------------------------------

    if (
        "ram" in q
        or "memory usage" in q
    ):

        memory = psutil.virtual_memory()

        used = memory.used / (1024 ** 3)
        total = memory.total / (1024 ** 3)

        return (
            f"Memory usage is {_pct(memory.percent)}. "
            f"About {used:.1f} gigabytes are in use "
            f"out of {total:.1f} gigabytes."
        )


    # ------------------------------------------------------------
    # DISK
    # ------------------------------------------------------------

    if (
        "disk" in q
        or "storage" in q
    ):

        drive = (
            os.environ.get("SystemDrive", "C:")
            + "\\"
        )

        total, used, free = shutil.disk_usage(
            drive
        )

        return (
            f"System drive usage is "
            f"{used / total * 100:.0f} percent. "
            f"{free / (1024 ** 3):.1f} gigabytes are free."
        )


    # ------------------------------------------------------------
    # GPU
    # ------------------------------------------------------------

    if "gpu" in q:

        answer = _gpu_status()

        if answer:
            return answer

        return (
            "I could not read the NVIDIA GPU status locally."
        )


    # ------------------------------------------------------------
    # WINDOWS / OS
    # ------------------------------------------------------------

    if (
        "windows version" in q
        or "operating system" in q
    ):

        return (
            f"This computer is running "
            f"{platform.system()} {platform.release()}, "
            f"build {platform.version()}."
        )


    # ------------------------------------------------------------
    # NETWORK
    # ------------------------------------------------------------

    if "network" in q:

        active = []

        stats = psutil.net_if_stats()

        for name, info in stats.items():

            if info.isup:
                active.append(name)

        if not active:
            return (
                "I do not see an active network interface."
            )

        return (
            "Active network interfaces are "
            + ", ".join(active[:5])
            + "."
        )


    # ------------------------------------------------------------
    # SYSTEM STATUS
    # ------------------------------------------------------------

    if (
        "system status" in q
        or "pc status" in q
        or "computer status" in q
    ):

        cpu = psutil.cpu_percent(
            interval=0.15
        )

        memory = psutil.virtual_memory()

        battery = psutil.sensors_battery()

        parts = [
            f"CPU {cpu:.0f} percent",
            f"memory {memory.percent:.0f} percent",
        ]

        if battery is not None:
            parts.append(
                f"battery {battery.percent:.0f} percent"
            )

        return (
            "System status: "
            + ", ".join(parts)
            + "."
        )


    return None
