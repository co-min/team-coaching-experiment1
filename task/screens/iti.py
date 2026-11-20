import random

from psychopy import core

from config import settings as S
from recording.frame_logger import set_onset, log_frame
from task.screens.instructions import check_escape


def run_gaussian_iti(win, global_clock, frame_log,
                     min_t=S.ITI_MIN, max_t=S.ITI_MAX, mean_t=S.ITI_MEAN, sd_t=S.ITI_SD):
    """가우시안 분포(min/max 클램핑)의 랜덤한 시간 동안 빈 화면(ITI)을 띄우고 로그를 남깁니다."""
    iti_duration = random.gauss(mean_t, sd_t)
    iti_duration = max(min_t, min(iti_duration, max_t))

    phase_clock = core.Clock()
    frame_idx = 0

    while phase_clock.getTime() < iti_duration:
        flip_time = win.flip()

        if frame_idx == 0:
            frame_log = set_onset(frame_log, flip_time)
            marker = f"iti_onset_dur_{iti_duration:.3f}"
        else:
            marker = ""

        frame_log = log_frame(frame_log, frame_idx, flip_time, global_clock.getTime(), marker)
        frame_idx += 1
        check_escape(win)

    return frame_log
