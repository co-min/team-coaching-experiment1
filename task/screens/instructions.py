from psychopy import core, event, visual, gui

from config import settings as S


def check_escape(win: visual.Window) -> None:
    if event.getKeys(keyList=["escape"]):
        win.close()
        core.quit()


def get_subject_info() -> dict:
    dlg = gui.Dlg(title="Team Managing Task")
    dlg.addField("Subject ID:", "001")
    dlg.addField("Session:",    "1")
    data = dlg.show()
    if not dlg.OK:
        core.quit()
    return {
        "subject_id": data[0].strip(),
        "session":    data[1].strip(),
    }


def show_instructions(win, text: str, advance_key: str = "space") -> None:
    event.clearEvents()
    visual.TextStim(
        win, text=text, font=S.FONT, pos=(0, 0), height=42,
        color="white", wrapWidth=1400, bold=True,
    ).draw()
    win.flip()
    event.waitKeys(keyList=[advance_key])
    event.clearEvents()


def show_message(win, text: str, duration: float = 2.5) -> None:
    """Display a brief timed message with no input required."""
    stim  = visual.TextStim(win, text=text, font=S.FONT, color='white', height=45,
                            wrapWidth=800, bold=True)
    clock = core.Clock()
    while clock.getTime() < duration:
        check_escape(win)
        stim.draw()
        win.flip()
