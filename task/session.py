"""
session.py
----------
Pre-experiment setup: subject dialog, window, LabJack, Neon.
Returns everything the task needs in one SessionContext.
"""

import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional

from psychopy import visual, monitors

from config import settings as S
from hardware.labjack import init_labjack
from hardware.neon import (
    NeonEventClient, NullNeonClient, check_neon_ready, create_neon_apriltags,
)
from task.screens.instructions import get_subject_info


@dataclass
class SessionContext:
    subject_id:        str
    session_id:        str
    win:               Any
    handle:            Any              # LabJack handle or None
    neon_client:       Any              # NeonEventClient | NullNeonClient
    neon_recording_id: Optional[str]
    apriltags:         List = field(default_factory=list)   # keep refs alive (AutoDraw)


def create_window() -> visual.Window:
    mon = monitors.Monitor(S.MONITOR_NAME)
    # TODO: set mon.setSizePix(), mon.setWidth(), mon.setDistance()
    #       to match your physical setup for correct visual-angle scaling.
    return visual.Window(
        size=S.WINDOW_SIZE,
        fullscr=S.WINDOW_FULLSCR,
        units=S.WINDOW_UNITS,
        monitor=mon,
        color=S.BACKGROUND_COLOR,
        colorSpace="hex",
        allowGUI=True,
        winType="pyglet",
        screen=S.SCREEN_NUMBER,
    )


def _connect_neon(win, subject_id: str, session_id: str):
    """Return (neon_client, recording_id, apriltags)."""
    if not S.USE_NEON:
        return NullNeonClient(), None, []

    print("• Neon 장치 확인 중 ...")
    if not check_neon_ready(S.NEON_DISCOVERY_TIMEOUT_S):
        print("✗ Neon 준비 안 됨 — Companion 앱에서 녹화를 시작한 뒤 재실행하세요.")
        sys.exit(1)
    print("✓ Neon 준비 완료")

    apriltags = create_neon_apriltags(win, S.NEON_APRILTAG_POSITIONS, S.NEON_APRILTAG_SIZE)
    try:
        client = NeonEventClient(
            subject_id=subject_id,
            session_id=session_id,
            discovery_timeout_s=S.NEON_DISCOVERY_TIMEOUT_S,
            retry_interval_s=S.NEON_RETRY_INTERVAL_S,
        )
        return client, client.start_session(), apriltags
    except RuntimeError as e:
        print(f" Neon not found → running without eye-tracker ({e})")
        return NullNeonClient(), None, apriltags


def start_session() -> SessionContext:
    """Run all pre-experiment setup and return initialized state."""
    info       = get_subject_info()
    subject_id = info["subject_id"]
    session_id = datetime.now().strftime("%Y%m%dT%H%M%S")

    win    = create_window()
    handle = init_labjack(S.LABJACK_DEVICE)
    print("LabJack handle:", handle)

    neon_client, recording_id, apriltags = _connect_neon(win, subject_id, session_id)
    print("Initialization complete.")

    return SessionContext(
        subject_id=subject_id,
        session_id=session_id,
        win=win,
        handle=handle,
        neon_client=neon_client,
        neon_recording_id=recording_id,
        apriltags=apriltags,
    )
