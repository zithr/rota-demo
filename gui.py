import requests
import sys
import FreeSimpleGUI as sg
import json
import pendulum
import asyncio
import re
import sys
from collections import defaultdict
from loguru import logger
from pyperclip import paste, copy
from multiprocessing import Process, Queue
from typing import List
from config import login_info
from main import get_active_volunteers, rota_pattern_to_dates
from pathlib import Path
from config import VERSION
from main import Volunteer
from main import (
    make_sign_ups,
    remove_all_sign_ups,
    get_vol_shifts_by_id,
    make_new_vol_report,
    find_a_shift,
)
from main import (
    adelete_all_shifts,
    acreate_multiple_shifts,
    abuild_rota_data,
    aget_all_vol_shifts_by_id,
    close_empty_shifts,
)
from branch_rota_window import create_branch_rota_window
from Listbox import Listbox

vol_rotas_path = Path(__file__).parent / "vol_rotas.json"
rota_template_path = Path(__file__).parent / "rota_template.json"
new_vol_rotas_path = Path(__file__).parent / "vol_rotas.json"

recent_months = (
    2  # shifts in last x months to count as recent, for all_vols_shifts.txt data
)
days_of_week = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def save_vol_rota(rotas: dict):
    with new_vol_rotas_path.open("w") as f:
        json.dump(rotas, f, indent=4, sort_keys=True)


def load_vol_rota() -> dict:
    with new_vol_rotas_path.open() as f:
        return json.load(f)


def load_old_vol_rota() -> dict:
    with vol_rotas_path.open() as f:
        return json.load(f)


def save_rota_template(template: dict):
    with rota_template_path.open("w") as f:
        json.dump(template, f, indent=4)


def load_rota_template() -> dict:
    with rota_template_path.open() as f:
        return json.load(f)


def rec_dd():
    return defaultdict(rec_dd)


def reformat_rota():
    vol_rota = load_old_vol_rota()
    new_rota = defaultdict(dict)
    for name, rota in vol_rota.items():
        new_rota[name]["rota"] = rota
        new_rota[name]["last_shift_scheduled"] = ""
        new_rota[name]["last_update"] = ""
    with new_vol_rotas_path.open("w") as f:
        json.dump(new_rota, f, indent=4, sort_keys=True)


# Attribute rota, last_shift and last_update to vols that have a stored rota on file
# The list of vols is pulled from Live, so also update any stored names that have changed
def assign_rota() -> List[Volunteer]:
    if VERSION == "DEMO":
        # DEMO - no fetching, create vols from json
        vols = []
        vols_rota = load_vol_rota()
        for v in vols_rota:
            note = vols_rota[v]["note"] if "note" in vols_rota[v] else ""
            vols.append(
                Volunteer(
                    v,
                    v,
                    vols_rota[v]["rota"],
                    vols_rota[v]["last_shift_scheduled"],
                    vols_rota[v]["last_update"],
                    note,
                )
            )
    else:
        vols: List[Volunteer] = get_active_volunteers()

    compare_update_name(vols)
    vol_rota: dict = load_vol_rota()
    for vol in vols:
        if vol.name in vol_rota:
            vol.rota = vol_rota[vol.name]["rota"]
            vol.last_shift_scheduled = vol_rota[vol.name]["last_shift_scheduled"]
            vol.last_update = vol_rota[vol.name]["last_update"]
            if "note" in vol_rota[vol.name]:
                vol.note = vol_rota[vol.name]["note"]
    return vols


# create a dict like {"Week 1": {"Monday": {"1900-2200": [Volunteer]}}}
def load_branch_rota(vols: List[Volunteer]) -> dict:
    branch_rota = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for i in range(8):
        for day in days_of_week:
            branch_rota[f"Week {i + 1}"][day]
    # loop over names from directory and check their rotas week by week (some vols have multiple shifts per week)

    for vol in vols:
        if len(vol.rota) > 3:
            for i, weekly in enumerate(vol.rota):
                for shift in weekly:
                    if shift == "OFF":
                        continue
                    day, time = shift.split(" ")
                    branch_rota[f"Week {i + 1}"][day][time].append(vol)
    # for k in branch_rota:
    #     print(f"-------{k}-------")
    #     for kk in branch_rota[k]:
    #         print(kk)
    #         for kkk, vvv in branch_rota[k][kk].items():
    #             print(kkk, [x.name for x in vvv])
    branch_rota = sort_branch_rota(branch_rota)
    return branch_rota


def sort_branch_rota(branch_rota: dict) -> dict:
    sorted_branch_rota = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for k in branch_rota:
        for kk in branch_rota[k]:
            sorted_keys = sorted(branch_rota[k][kk].keys())
            sorted_branch_rota[k][kk] = {
                key: branch_rota[k][kk][key] for key in sorted_keys
            }
    return sorted_branch_rota


# Someone's Live name might be changed/updated, so update stored name
def compare_update_name(vols: List[Volunteer]) -> None:
    vol_rota = load_vol_rota()
    for vol in vols:
        # every name has unique number, so just look for number
        vol_num = re.findall("([0-9]+)", vol.name)
        if not vol_num:
            continue
        vol_num = vol_num[0]
        for stored_name in vol_rota.keys():
            if vol_num in stored_name:
                if stored_name != vol.name:
                    # Remove old vol name and replace with new one, i.e. update key name
                    vol_rota[vol.name] = vol_rota.pop(stored_name)
                    save_vol_rota(vol_rota)
                    break
        # if vol_num in vol.name:
        #     if name == vol.name:
        #         return
        #     print(vol.name, name)
        # vol_rota[vol.name] = vol_rota.pop(name)
        # save_vol_rota(vol_rota)


# Helper function for collapsable gui windows
def collapse(layout, key, visible=None):
    if not visible:
        visible = False
    return sg.pin(sg.Column(layout, key=key, visible=visible))


# Main window, most GUI stuff is implemented here
def main_window(session: requests.Session):
    sg.set_options(
        suppress_raise_key_errors=False,
        suppress_error_popups=False,
        suppress_key_guessing=False,
    )
    sg.theme("Dark Blue 3")

    def init_gui_vars():
        active_vol = ""
        vols = assign_rota()
        stored_rota = load_vol_rota()
        name_vals = []

        # Add prefixes to vol names...
        # [F] for a vol on Fixed Rota (if their rota is saved on file in stored_rota)
        # [!!] if their Fixed Rota is expiring in the next 2 months
        for vol in vols:
            tmp_name = ""
            if vol.name in stored_rota:
                tmp_name += "[F]"
                if len(stored_rota[vol.name]["last_shift_scheduled"]) > 3:
                    last_shift_scheduled = pendulum.from_format(
                        stored_rota[vol.name]["last_shift_scheduled"], "D MMM YYYY"
                    )
                    if last_shift_scheduled.subtract(months=2) < pendulum.now():
                        tmp_name += "[!!]"
            tmp_name += vol.name
            name_vals.append(tmp_name)

        gui_init_complete = False
        return (
            active_vol,
            vols,
            name_vals,
            gui_init_complete,
        )

    (
        active_vol,
        vols,
        name_vals,
        gui_init_complete,
    ) = init_gui_vars()
    full_name_vals = name_vals[:]
    fix_toggle = False
    expiring_toggle = False
    queue = Queue()
    pr = Process(target=do_rota_init, args=(queue,)).start()

    left_col = sg.Column(
        [
            [
                Listbox(
                    values=name_vals,
                    select_mode=sg.SELECT_MODE_EXTENDED,
                    size=(60, 30),
                    bind_return_key=True,
                    key="-VOLUNTEER LIST-",
                    enable_events=True,
                )
            ],
            [
                sg.B("View Fixed", k="-FIXTOGGLE-"),
                sg.B("View Expiring", k="-EXPIRINGTOGGLE-"),
            ],
        ],
        element_justification="l",
        expand_x=True,
        expand_y=True,
    )

    right_col = [
        [
            sg.T("Rota", size=(25, 2), font="Default 10", pad=(0, 0), k="-ROTA TITLE-"),
            sg.B("Remove from shifts", k="-BUTTON REMOVE-", visible=False),
            sg.B("Copy Rota", k="-BUTTON COPY-", visible=False),
        ],
        [
            sg.Listbox(
                values=[],
                size=(70, 20),
                bind_return_key=True,
                key="-DISPLAY ROTA-",
            )
        ],
        [
            sg.Button("Edit Rota"),
            sg.Button("Add to Live"),
            sg.Button("Delete Rota", button_color="red"),
        ],
    ]

    layout = [
        [
            sg.B("Branch Rota", button_color="green"),
            sg.B("New Vol Report", button_color="teal"),
            sg.B("Download Shift Log", button_color="purple", k="-UPCOMING-"),
            sg.B("Close shifts", button_color="black"),
            sg.Button("Add shifts"),
            sg.Button("Delete shifts"),
            sg.B("Rota Template"),
            sg.B("Shift Gaps", button_color="blue"),
        ],
        [sg.Text("Available Rotas:")],
        [
            sg.Pane(
                [
                    left_col,
                    sg.Column(
                        right_col,
                        element_justification="l",
                        expand_x=True,
                        expand_y=True,
                    ),
                ],
                orientation="h",
                relief=sg.RELIEF_SUNKEN,
                k="-PANE-",
                show_handle=False,
            )
        ],
        [sg.B("Exit")],
    ]

    window = sg.Window("Rota Editor", layout, finalize=True)

    # Listbox colouring test, working
    # test_lb = window["-VOLUNTEER LIST-"]
    # settings = [
    #     (3, "Red", "red", "white"),
    # ]
    # for i, v, bg, fg in settings:
    #     test_lb.item(i, value=v, bg=bg, fg=fg)
    while True:
        event, values = window.read()
        if event == sg.WIN_CLOSED or event == "Exit":
            break
        if not gui_init_complete:
            if not queue.empty():
                init_rota = queue.get()
                gui_init_complete = True
                if VERSION == "DEMO":
                    logger.info("Mock data load complete")
                else:
                    logger.info("Background initial rota download complete")
        # toggle showing vols with Fixed tag, [F], for easier viewing
        if event == "-FIXTOGGLE-":
            if fix_toggle == False:
                name_vals = [x for x in full_name_vals if x.startswith("[F]")]
            else:
                name_vals = full_name_vals[:]
            fix_toggle = not fix_toggle
            window["-VOLUNTEER LIST-"].update(name_vals)
        # toggle showing vols with Expiring tag, [!!], for easier viewing
        if event == "-EXPIRINGTOGGLE-":
            if expiring_toggle == False:
                name_vals = [x for x in full_name_vals if x.startswith("[F][!!]")]
                fix_toggle = True
            else:
                name_vals = full_name_vals[:]
                fix_toggle = False
            expiring_toggle = not expiring_toggle
            window["-VOLUNTEER LIST-"].update(name_vals)
        if event == "Rota Template":
            window_template, template = handle_show_rota_template()
            while True:
                event, values = window_template.read()
                if event == sg.WIN_CLOSED:
                    break
                if event == "Cancel":
                    window_template.close()
                    window_template = None
                    break
                if event == "-WEEK LIST-":
                    # last_active_values = active_values
                    # active_values = values
                    # verify_save_or_switch(last_active_values)  # doesn't work, since values immediately gets updated to new week
                    window_template["-TEMPLATE TITLE-"].update(values["-WEEK LIST-"][0])
                    for day in days_of_week:
                        window_template[f"-TEMPLATE {day.upper()}-"].update(
                            ", ".join(template[values["-WEEK LIST-"][0]][f"{day}"])
                        )
                if event == "Save":
                    handle_template_save(values, template)
                    sg.PopupOK("Template saved")
                if event == "Upload Rota":
                    window_upload = create_rota_upload_window()
                    while True:
                        event, values = window_upload.read()
                        if event == sg.WIN_CLOSED:
                            break
                        if event == "Cancel":
                            window_upload.close()
                            window_template = None
                            break
                        if event == "Create":
                            res = handle_rota_upload(
                                session,
                                values["-START ROTA DATE-"],
                                values["-ROTA MONTHS-"],
                            )
                            if res:
                                window_upload.close()
                                window_template = None
                                break
        if event == "-VOLUNTEER LIST-":
            for x in values["-VOLUNTEER LIST-"]:  # dont need for loop..
                for vol in vols:
                    if vol.name in x:
                        if not vol.rota:
                            window["-DISPLAY ROTA-"].update(["No rota found"])
                        else:
                            shift_display = [
                                f"Last shift scheduled: {vol.last_shift_scheduled}"
                            ]
                            for i, week in enumerate(vol.rota):
                                shift_display.append(f"{i + 1}: {', '.join(week)}")
                            shift_display.extend(
                                ["", f"Last updated: {vol.last_update}"]
                            )
                            if vol.note:
                                shift_display.extend(["", f"Note: {vol.note}"])
                            window["-DISPLAY ROTA-"].update(shift_display)
                            window["-BUTTON REMOVE-"].update(visible=True)
                            window["-BUTTON COPY-"].update(visible=True)
                        window["-ROTA TITLE-"].update(f"Rota - {vol.name}")
                        active_vol = vol
                        # print(f"rota of {vol.name}: {vol.rota}")

        # Edit rota on double clicking someone's rota
        if event == "-DISPLAY ROTA-":
            window.write_event_value("Edit Rota", values)
        if event == "-BUTTON REMOVE-":
            vol_to_remove = active_vol
            window_remove_vol = create_remove_vols_shifts_window(vol_to_remove)
            while True:
                event, values = window_remove_vol()
                if event == sg.WIN_CLOSED:
                    break
                if event == "Cancel":
                    window_remove_vol.close()
                    window_remove_vol = None
                    break
                if event == "Remove":
                    res = handle_remove_vol(session, vol_to_remove, values)
                    if not res:
                        continue
                    sg.Popup(f"{vol_to_remove.name} removed from {res} shifts")
        if event == "-BUTTON COPY-":
            # Copy rota to clipboard
            rota_dict = load_vol_rota()
            if len(rota_dict[active_vol.name]["rota"]) < 8:
                logger.warning(f"Valid rota not found for {active_vol.name}")
                continue
            rota_text = f"{active_vol.name}'s Rota\n\n"
            for i in range(8):
                rota_text += f"Week {i + 1}: {', '.join(rota_dict[active_vol.name]['rota'][i])}\n"
            logger.info(f"{active_vol.name} rota copied to clipboard.")
            copy(rota_text)
            continue
        if event == "Delete Rota":
            if not sg.PopupYesNo(f"Delete {active_vol.name} rota?"):
                continue
            rota_dict = load_vol_rota()
            rota_dict.pop(active_vol.name)
            save_vol_rota(rota_dict)
            window["-DISPLAY ROTA-"].update(["No rota found"])
        if event == "Add to Live":
            if not active_vol:
                sg.Popup("Select volunteer first")
                continue

            if (
                sg.PopupOKCancel(f"Add {active_vol.name} to Live", font="Any 20")
                == "OK"
            ):
                window3 = create_finalise_post_window()
                while True:
                    event, values = window3.read()
                    if event == sg.WIN_CLOSED:
                        break
                    if event == "Cancel":
                        window3.close()
                        window3 = None
                        break
                    if event == "Post":
                        try:
                            start_date = pendulum.from_format(
                                values["-START DATE-"], "DD.MM.YY"
                            )
                        except ValueError:
                            sg.PopupError(
                                "Invalid syntax for start date, must be DD.MM.YY"
                            )
                            continue
                        if start_date < pendulum.today():
                            sg.PopupError("Start date cannot be earlier than today!")
                            continue
                        if int(values["-MONTH NUM-"]) not in range(1, 13):
                            sg.PopupError("Number of months must be between 1-12")
                            continue
                        sg.PopupOK(
                            "Making signups...",
                            auto_close=True,
                            auto_close_duration=4,
                            non_blocking=True,
                        )
                        pattern = active_vol.rota
                        thrd = Process(
                            target=do_make_sign,
                            args=(
                                session,
                                active_vol.name,
                                pattern,
                                start_date,
                                int(values["-MONTH NUM-"]),
                            ),
                        ).start()
                        window3.close()
                        window3 = None
                        break
        if event == "-UPCOMING-":
            prb_only = False
            num_months = sg.popup_get_text(
                "Number of months:",
                default_text="2",
                no_titlebar=True,
                size=(15, 5),
                grab_anywhere=True,
            )
            if not num_months:
                continue
            num_months = int(num_months)
            ans = sg.PopupYesNo("Probationers only?")
            if not ans:
                continue
            if ans == "Yes":
                prb_only = True
            if VERSION == "DEMO":
                logger.info("Download shift log function disabled in demo version")
                continue
            Process(
                target=do_get_all_vol_shifts,
                args=(vols, prb_only),
            ).start()

        if event == "Edit Rota":
            if not active_vol:
                sg.popup("No vol selected")
                continue
            window2 = create_edit_window(active_vol)

            # EDIT VOLS ROTA WINDOW
            while True:
                event2, values = window2.read()
                if event2 == sg.WIN_CLOSED:
                    break
                if event2 == "Cancel":
                    window2.close()
                    window2 = None
                    break
                if event2 == "Read Clipboard":
                    clipboard_list = handle_read_clipboard()
                    if not clipboard_list:
                        logger.info("Clipboard read failed")
                        continue
                    for i, clipboard_week in enumerate(clipboard_list):
                        window2[f"-WEEK {i + 1}-"].update(clipboard_week)
                if event2 == "Save":
                    multi_rota = []
                    for i in range(8):
                        week_shifts_value = values[f"-WEEK {i + 1}-"].replace("–", "-")
                        if "," in week_shifts_value:
                            week_shifts_value = week_shifts_value.split(",")
                            for enu, shift_time in enumerate(week_shifts_value):
                                week_shifts_value[enu] = shift_time.strip().capitalize()
                            multi_rota.append(week_shifts_value)
                        else:
                            multi_rota.append([week_shifts_value.capitalize()])
                    new_rota = validate_input(multi_rota)
                    if new_rota:
                        rota_dict = load_vol_rota()
                        active_vol.rota = new_rota
                        if active_vol.name not in rota_dict:
                            rota_dict[active_vol.name] = {
                                "last_shift_scheduled": "",
                                "last_update": "",
                                "rota": [],
                                "note": "",
                            }
                        new_note = values["-NOTE-"]
                        rota_dict[active_vol.name]["note"] = new_note
                        rota_dict[active_vol.name]["rota"] = new_rota
                        active_vol.last_update = pendulum.today().format("D MMM YY")
                        rota_dict[active_vol.name]["last_update"] = (
                            active_vol.last_update
                        )
                        active_vol.note = new_note
                        save_vol_rota(rota_dict)
                        window2.close()
                        window2 = None
                        shift_display = [
                            f"Last shift scheduled: {active_vol.last_shift_scheduled}"
                        ]
                        for i, week in enumerate(active_vol.rota):
                            shift_display.append(f"{i + 1}: {', '.join(week)}")
                        shift_display.extend(
                            ["", f"Last updated: {active_vol.last_update}"]
                        )
                        if new_note:
                            shift_display.extend(["", f"Note: {new_note}"])
                        window["-DISPLAY ROTA-"].update(shift_display)
                        logger.info("Input rota/note validated and saved successfully")
                        break
                # END EDIT VOLS ROTA

        # MAIN WINDOW

        # Branch Rota, a view only window -> no reads
        if event == "Branch Rota":
            branch_rota = load_branch_rota(vols)
            window_br = create_branch_rota_window(branch_rota)
            # while True:
            #     event, values = window_br.read()
            #     if event == sg.WIN_CLOSED or event == "Exit":
            #         window_br.close()
            #         window_br = None
            #         break
        if event == "New Vol Report":
            if VERSION == "DEMO":
                logger.info("New Vol Report function disabled in demo version")
                continue
            logger.info("Creating new volunteer report...")
            make_new_vol_report(vols)
        # Create empty shifts on Live with pattern
        if event == "Add shifts":
            thrd = None
            window_add = create_add_shift_window()

            # ADD SHIFTS TO LIVE
            while True:
                event, values = window_add.read()
                if event == sg.WIN_CLOSED:
                    break
                if event == "Cancel":
                    if thrd:
                        thrd.kill()
                    window_add.close()
                    window_add = None
                    break
                if event == "-ADD REPEAT-":
                    window_add["-REPEAT OPTIONS-"].update(
                        visible=values["-ADD REPEAT-"]
                    )
                if event == "Create":
                    thrd = handle_add_shifts(session, values, window_add)
                    if not thrd:
                        continue
                    window_add.close()
                    window_add = None
                    break

        if event == "Shift Gaps":
            # Shift gaps for next 10 days, need to use Queue or such to get the text directly from Process
            Process(
                target=do_shift_gaps_message,
                args=(
                    pendulum.now().format("DD.MM.YY"),
                    # pendulum.now().next(pendulum.MONDAY).format("DD.MM.YY")
                    pendulum.now().add(days=10).format("DD.MM.YY"),
                ),
            ).start()
            continue

        # MAIN WINDOW
        if event == "Delete shifts":
            window_del = create_delete_shift_window()

            # DELETE SHIFTS FROM LIVE
            while True:
                event, values = window_del.read()
                if event == sg.WIN_CLOSED:
                    break
                if event == "Cancel":
                    window_del.close()
                    window_del = None
                    break
                if event == "Delete":
                    try:
                        start_del_date = pendulum.from_format(
                            values["-DEL START-"], "DD.MM.YY"
                        )
                        end_del_date = pendulum.from_format(
                            values["-DEL END-"], "DD.MM.YY"
                        )
                    except ValueError as e:
                        sg.PopupError(f"Invalid dates: {e}")
                        continue
                    if start_del_date > end_del_date:
                        sg.PopupError("End date must be after start date!")
                        continue
                    if not values["-DEL TYPE-"]:
                        sg.PopupError("Select shift type from drop down!")
                        continue
                    # TODO add Hours of Need
                    if values["-DEL TYPE-"] == "Both":
                        del_types = ["(Duty Room)", "(Leader)"]
                    else:
                        del_types = [values["-DEL TYPE-"]]
                    empty_only = values["-DEL EMPTY-"]
                    window_del["-MSG-"].update("Deleting shifts...")
                    Process(
                        target=do_adelete,
                        args=(
                            session,
                            start_del_date,
                            end_del_date,
                            del_types,
                            empty_only,
                        ),
                    ).start()
                    window_del.close()
                    window_del = None
                    break

        # MAIN WINDOW
        if event == "Close shifts":
            window_close = create_close_shifts_window()

            # CLOSE SHIFTS ON LIVE
            while True:
                event, values = window_close.read()
                if event == sg.WIN_CLOSED:
                    break
                if event == "Cancel":
                    window_close.close()
                    window_close = None
                    break
                if event == "Close":
                    try:
                        start_close_date = pendulum.from_format(
                            values["-CLOSE START-"], "DD.MM.YY"
                        )
                        end_close_date = pendulum.from_format(
                            values["-CLOSE END-"], "DD.MM.YY"
                        )
                    except ValueError as e:
                        sg.PopupError(f"Invalid dates: {e}")
                        continue
                    if start_close_date > end_close_date:
                        sg.PopupError("End date must be after start date!")
                        continue

                    window_close["-MSG-"].update("Closing shifts...")
                    Process(
                        target=do_close_empty_shifts,
                        args=(
                            start_close_date,
                            end_close_date,
                        ),
                    ).start()
                    window_close.close()
                    window_close = None
                    break
    window.close()


def do_rota_init(queue):
    ret = None
    # Windows asyncio fix
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # DEMO - no fetching
    # asyncio.run(abuild_rota_data(queue=queue))
    queue.put(ret)


def do_shift_gaps_message(start_date: str, end_date: str) -> str:
    """
    Returns formatted message roughly suitable for emailing
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    logger.info("Writing shift gaps message...")
    start = pendulum.from_format(start_date, "DD.MM.YY")
    end = pendulum.from_format(end_date, "DD.MM.YY")
    gaps = asyncio.run(find_a_shift(start, end))
    normal_message = """Hi all,
Please see next week's shift gaps below and let me know if you can help, or sign up directly:

"""
    leader_message = """Dear leaders,
Please see next week's leader gaps below and let me know if you can help, or sign up directly:

"""
    for gap in gaps:
        if gap[0].lower() in ["duty room", "hours of need"]:
            if len(gap) < 3:
                normal_message += f"{gap[1]}\n"
            else:
                normal_message += f"{gap[1]}   {gap[2]}\n"
        elif gap[0].lower() == "leader":
            leader_message += f"{gap[1]}\n"
    normal_message += "Best,\n\n"
    leader_message += "Best,"
    logger.info("Gaps message on clipboard.")
    copy(normal_message + leader_message)
    return normal_message + leader_message


def do_get_all_vol_shifts(
    vols: List[Volunteer], prb_only: bool = False, num_months: int = 2
):
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    if prb_only:
        vols = [vol for vol in vols if "Prb" in vol.name]
    vol_all_shifts = asyncio.run(aget_all_vol_shifts_by_id(vols))
    out = [
        f"Name\tRecent ({num_months} months) Duties\tRecent Hours of Need\tLast Shift\tRecent Total\tUpcoming Duty\tUpcoming Hours of Need\tUpcoming Total"
    ]
    for get_shifts in vol_all_shifts:
        if not get_shifts:
            continue
        if len(get_shifts) < 2:
            print(f"{get_shifts[0]} has no shifts")
            out.append(f"{get_shifts[0]}\t0\t0\tNone\t0\t0\t0\t0")
            continue
        recent = []
        recent_need = []
        upcom = []
        upcom_need = []
        latest_shift = None
        for sh in get_shifts[1:]:
            if (
                sh > pendulum.today().subtract(months=num_months)
                and sh < pendulum.today()
            ):
                if 22 <= sh.hour or sh.hour <= 5:
                    recent_need.append(sh)
                else:
                    recent.append(sh)
                if not latest_shift or latest_shift < sh:
                    latest_shift = sh
            if sh > pendulum.today():
                if 22 <= sh.hour or sh.hour <= 5:
                    upcom_need.append(sh)
                else:
                    upcom.append(sh)
        latest_shift_str = (
            f"{latest_shift.format('DD/MM/YYYY') if latest_shift else 'None'}"
        )
        out.append(
            f"{get_shifts[0]}\t{len(recent)}\t{len(recent_need)}\t{latest_shift_str}\t{len(recent) + len(recent_need)}\t{len(upcom)}\t{len(upcom_need)}\t{len(upcom) + len(upcom_need)}"
        )
    with open("all_vol_shifts.txt", "w+") as f:
        for line in out:
            f.write(f"{line}\n")


def do_acreate(
    _session, shifts_to_make: List[List[pendulum.DateTime]], shift_types: List[str]
):
    if VERSION == "DEMO":
        logger.info("Create shifts disabled in demo version")
        return
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # loop = asyncio.get_event_loop()
    # loop.run_until_complete(acreate_multiple_shifts(_session, shifts_to_make, shift_types))
    asyncio.run(acreate_multiple_shifts(_session, shifts_to_make, shift_types))


def do_adelete(
    _session,
    start_del_date: pendulum.DateTime,
    end_del_date: pendulum.DateTime,
    del_types: List[str],
    empty_only: bool,
):
    if VERSION == "DEMO":
        logger.info("Delete shifts disabled in demo version")
        return
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # loop = asyncio.get_event_loop()
    # loop.run_until_complete(adelete_all_shifts(_session, start_del_date, end_del_date, del_types, empty_only))
    asyncio.run(
        adelete_all_shifts(
            _session, start_del_date, end_del_date, del_types, empty_only
        )
    )


def do_close_empty_shifts(
    start_close_date: pendulum.DateTime, end_close_date: pendulum.DateTime
):
    if VERSION == "DEMO":
        logger.info("Close shifts disabled in demo version")
        return
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(close_empty_shifts(start_close_date, end_close_date))


def do_make_sign(
    session: requests.Session,
    name: str,
    pattern: List[List[str]],
    start_date: pendulum.DateTime,
    month_num: int,
):
    if VERSION == "DEMO":
        logger.info("Signup for shifts disabled in demo version")
        return
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    signed_shifts = asyncio.run(
        make_sign_ups(session, name, pattern, start_date, month_num)
    )
    if not signed_shifts:
        return
    update_latest_shift_date(name, max(signed_shifts))


def update_latest_shift_date(name: str, dt: pendulum.DateTime):
    rota = load_vol_rota()
    rota[name]["last_shift_scheduled"] = dt.format("D MMM YYYY")
    save_vol_rota(rota)


def create_edit_window(vol):
    sg.set_options(
        suppress_raise_key_errors=False,
        suppress_error_popups=False,
        suppress_key_guessing=False,
    )
    sg.theme("Dark Blue 3")
    label_width = 7

    display_rota = ""
    layout = [
        [sg.Text(f"Rota for {vol.name}")],
        [sg.T("e.g. Monday 0000-1500"), sg.Push(), sg.B("Read Clipboard")],
    ]

    for i in range(8):
        if not vol.rota:
            vol.rota = [""] * 8
        else:
            display_rota = (", ").join(vol.rota[i])
        layout += [
            [
                sg.Text(f"Week {i + 1}", size=(label_width, 1)),
                sg.Input(default_text=f"{display_rota}", key=f"-WEEK {i + 1}-"),
            ]
        ]

    layout += [[sg.HorizontalSeparator()]]
    layout += [
        [
            sg.Text("Note", size=(label_width, 1)),
            sg.I(default_text=f"{vol.note}", key="-NOTE-"),
        ]
    ]
    layout += [[sg.B("Save"), sg.B("Cancel")]]

    window = sg.Window("Edit", layout, finalize=True)
    return window


def create_finalise_post_window():
    sg.set_options(
        suppress_raise_key_errors=False,
        suppress_error_popups=False,
        suppress_key_guessing=False,
    )
    sg.theme("Dark Blue 3")
    layout = [
        [sg.Text(f"Enter start date: ")],
        [
            sg.Input(
                default_text=f"{pendulum.today().format('DD.MM.YY')}",
                s=(15, 1),
                key="-START DATE-",
            )
        ],
    ]
    layout += [
        [sg.T("Enter number of months to write rota (under 12): ")],
        [sg.I(default_text="10", s=(5, 1), key="-MONTH NUM-")],
    ]
    layout += [[sg.B("Post"), sg.B("Cancel")]]
    window = sg.Window("Upload Rota", layout, finalize=True)
    return window


def create_add_shift_window():
    sg.set_options(
        suppress_raise_key_errors=False,
        suppress_error_popups=False,
        suppress_key_guessing=False,
    )
    sg.theme("Dark Blue 3")

    today = pendulum.today()
    repeat_options = [
        [
            sg.T("Repeat every x weeks (1 for every week): "),
            sg.I(s=8, default_text="0", key="-ADD REPEAT WEEK-"),
        ]
    ]
    repeat_options += [
        [
            sg.T("Repeat until date: "),
            sg.I(
                s=8,
                default_text=today.add(months=6).format("DD.MM.YY"),
                key="-ADD REPEAT END-",
            ),
        ]
    ]
    layout = [
        [
            sg.T("Enter date (31.03.22): "),
            sg.I(
                s=15,
                default_text=today.format("DD.MM.YY"),
                key="-ADD DATE-",
            ),
        ]
    ]
    layout += [
        [
            sg.T("Enter start time (1900): "),
            sg.I(s=15, default_text="1900", key="-ADD START-"),
        ]
    ]
    layout += [
        [
            sg.T("Enter end time (2200): "),
            sg.I(s=15, default_text="2200", key="-ADD END-"),
        ]
    ]
    # TODO add Hours of Need
    layout += [
        [
            sg.T("Shift types:"),
            sg.InputCombo(
                ("(Duty Room)", "(Leader)", "Both", "(Tutored)"),
                size=10,
                default_value="Both",
                key="-ADD TYPE-",
            ),
        ]
    ]
    layout += [[sg.Checkbox("Repeat shift?", key="-ADD REPEAT-", enable_events=True)]]
    layout += [[collapse(repeat_options, "-REPEAT OPTIONS-")]]
    layout += [[sg.T("Press Create if you're sure...", key="-ADD TEXT-")]]
    layout += [[sg.B("Create", button_color="green"), sg.B("Cancel")]]
    window = sg.Window("Add Shifts", layout, finalize=True)
    return window


def handle_add_shifts(session, values, window=None):
    shifts_to_make = []
    try:
        start_dt = pendulum.from_format(
            f"{values['-ADD DATE-']}T{values['-ADD START-']}", "DD.MM.YY[T]HHmm"
        )
        end_dt = pendulum.from_format(
            f"{values['-ADD DATE-']}T{values['-ADD END-']}", "DD.MM.YY[T]HHmm"
        )
    except ValueError as e:
        sg.PopupError(f"Invalid date/time syntax, {e}")
        return
    if end_dt < start_dt:
        end_dt = end_dt.add(days=1)
        if pendulum.period(start_dt, end_dt).hours > 8:
            sg.PopupError("Shift is longer than 8 hours, check start/end times!")
            return
    # TODO add Hours of Need
    shift_types = [values["-ADD TYPE-"]]
    if shift_types == ["Both"]:
        shift_types = ["(Duty Room)", "(Leader)"]
    if values["-ADD REPEAT-"]:
        if int(values["-ADD REPEAT WEEK-"]) not in range(1, 17):
            sg.PopupError("Repeat must be between 1 and 16")
            return
        try:
            end_repeat_dt = pendulum.from_format(values["-ADD REPEAT END-"], "DD.MM.YY")
            if end_repeat_dt < start_dt:
                sg.PopupError("'Repeat until date' must be after start date!")
                return
            if end_repeat_dt > pendulum.today().add(months=18):
                sg.PopupError(
                    "'Repeat until date' is too far away (must be under 18 months away)"
                )
                return
        except ValueError as e:
            sg.PopupError(f"Invalid 'Repeat until date' syntax, {e}")
        while start_dt < end_repeat_dt:
            shifts_to_make.append([start_dt, end_dt])
            start_dt = start_dt.add(weeks=int(values["-ADD REPEAT WEEK-"]))
            end_dt = end_dt.add(weeks=int(values["-ADD REPEAT WEEK-"]))
    else:
        shifts_to_make.append([start_dt, end_dt])

    if sg.PopupOKCancel(f"Create {len(shifts_to_make)} shifts?") != "OK":
        return
    t = Process(target=do_acreate, args=(session, shifts_to_make, shift_types))
    t.start()
    # formatted = [f"{x[0].format('ddd DD.MM.YY @ HHmm')}-{x[1].format('HHmm')}" for x in shifts_to_make]
    # print(formatted)
    return t


def create_delete_shift_window():
    sg.set_options(
        suppress_raise_key_errors=False,
        suppress_error_popups=False,
        suppress_key_guessing=False,
    )
    # TODO add Hours of Need
    sg.theme("Dark Blue 3")
    layout = [
        [
            sg.T("Enter start date (DD.MM.YY): "),
            sg.I(
                s=(15),
                key="-DEL START-",
                default_text=f"{pendulum.today().format('DD.MM.YY')}",
            ),
        ]
    ]
    layout += [
        [
            sg.T("Enter end date (DD.MM.YY): "),
            sg.I(
                s=(15),
                key="-DEL END-",
                default_text=f"{pendulum.today().add(weeks=1).format('DD.MM.YY')}",
            ),
        ]
    ]
    layout += [
        [
            sg.T("Shift types:"),
            sg.InputCombo(
                ("(Duty Room)", "(Leader)", "Both", "(Tutored)"),
                size=10,
                default_value="(Tutored)",
                key="-DEL TYPE-",
            ),
        ]
    ]
    layout += [
        [sg.Checkbox("Delete only empty shifts", default=True, key="-DEL EMPTY-")]
    ]
    layout += [[sg.T("Click delete if you're sure...", key="-MSG-", s=30)]]
    layout += [[sg.B("Delete", button_color="red"), sg.B("Cancel")]]
    window = sg.Window("Delete Shifts", layout, finalize=True)
    return window


def create_close_shifts_window():
    sg.set_options(
        suppress_raise_key_errors=False,
        suppress_error_popups=False,
        suppress_key_guessing=False,
    )
    # TODO add Hours of Need
    sg.theme("Dark Blue 3")
    layout = [
        [
            sg.T("Enter start date (DD.MM.YY): "),
            sg.I(
                s=(15),
                key="-CLOSE START-",
                default_text=f"{pendulum.today().format('DD.MM.YY')}",
            ),
        ]
    ]
    layout += [
        [
            sg.T("Enter end date (DD.MM.YY): "),
            sg.I(
                s=(15),
                key="-CLOSE END-",
                default_text=f"{pendulum.today().end_of('week').format('DD.MM.YY')}",
            ),
        ]
    ]

    layout += [[sg.T("Click close to confirm", key="-MSG-", s=30)]]
    layout += [[sg.B("Close", button_color="red"), sg.B("Cancel")]]
    window = sg.Window("Close Shifts", layout, finalize=True)
    return window


def handle_read_clipboard():
    syn_error = []
    c_text = paste()
    if "week" not in c_text.lower():
        logger.warning(f"Invalid clipboard data, found:\n{c_text}")
        return
    c_text = re.sub("Week ([1-8])", r"Week \1:", c_text)
    c_text = re.sub(r"\s*[-–]\s*", "-", c_text).splitlines()
    list_from_clip = [x.split(":")[-1].strip() for x in c_text if x]
    list_from_clip = [x.strip() for x in list_from_clip if x]
    if len(list_from_clip) != 8:
        sg.PopupError("Clipboard rota is not 8 weeks long.")
        return
    for i, t in enumerate(list_from_clip):
        if t.lower() in ["off", "no duty"]:
            continue
        if not re.match(r"\w+ \d{4}-\d{4}", t):
            syn_error.append(str(i + 1))
    if syn_error:
        logger.warning(f"Errors found in Weeks {(', ').join(syn_error)}")
        return

    return list_from_clip


def handle_show_rota_template():
    template = load_rota_template()

    sg.set_options(
        suppress_raise_key_errors=False,
        suppress_error_popups=False,
        suppress_key_guessing=False,
    )
    sg.theme("Dark Blue 3")

    left_col = sg.Column(
        [
            [
                sg.Listbox(
                    values=[k for k in template],
                    select_mode=sg.SELECT_MODE_EXTENDED,
                    size=(50, 20),
                    bind_return_key=True,
                    key="-WEEK LIST-",
                    enable_events=True,
                )
            ],
        ],
        element_justification="l",
        expand_x=True,
        expand_y=True,
    )
    right_col = sg.Column(
        [
            [sg.T("Week 1", size=(25, 1), k="-TEMPLATE TITLE-")],
            *[
                [
                    sg.T(f"{day}: "),
                    sg.I(
                        default_text=f"{', '.join(template['Week 1'][day])}",
                        expand_x=True,
                        k=f"-TEMPLATE {day.upper()}-",
                    ),
                ]
                for day in days_of_week
            ],
            [sg.VPush()],
            [
                sg.Push(),
                sg.Button("Save"),
                sg.Button("Cancel"),
                sg.B("Upload Rota"),
                sg.Push(),
            ],
        ]
    )
    layout = [
        [
            sg.Pane(
                [left_col, right_col],
                orientation="h",
                relief=sg.RELIEF_SUNKEN,
                k="-TEMPLATE PANE-",
            )
        ]
    ]
    window = sg.Window("Rota Template", layout, finalize=True)
    return window, template


def handle_template_save(values: dict, template: dict):
    for day in days_of_week:
        new_times = values[f"-TEMPLATE {day.upper()}-"].replace(" ", "").split(",")
        if not new_times:
            sg.Popup(f"Saving failed on {day}")
            return
        new_times.sort()
        template[values["-WEEK LIST-"][0]][day] = new_times
    save_rota_template(template)


def create_rota_upload_window():
    sg.set_options(
        suppress_raise_key_errors=False,
        suppress_error_popups=False,
        suppress_key_guessing=False,
    )
    sg.theme("Dark Blue 3")
    layout = [
        [sg.T("Create shifts on Live for a number of months:")],
        [sg.T("Start at (dd.mm.yy): "), sg.I(k="-START ROTA DATE-", s=10)],
        [sg.T("Number of months:  "), sg.I(k="-ROTA MONTHS-", s=10)],
        [sg.B("Create"), sg.B("Cancel")],
    ]
    window = sg.Window("Create Live Rota", layout=layout, finalize=True)
    return window


def handle_rota_upload(session, start_date: str, rota_months: str):
    try:
        start_dt = pendulum.from_format(start_date, "DD.MM.YY")
    except ValueError as e:
        sg.Popup("Invalid start date")
        return
    try:
        rota_months = int(rota_months)
    except ValueError:
        sg.Popup("Number of months must be a number.")
        return
    if rota_months not in range(1, 19):
        sg.Popup("Number of months must be between 1-18")
        return
    template = load_rota_template()
    shifts = rota_pattern_to_dates(session, template, start_dt, rota_length=rota_months)
    if (sg.PopupOKCancel(f"Create {len(shifts)} shifts?")) != "OK":
        return
    acreate_multiple_shifts(session, shifts, shift_types="[Both]")
    return True


def verify_save_or_switch(last_values: dict) -> bool:
    if not last_values:
        return
    template = load_rota_template()
    difference_found = False
    for day in days_of_week:
        new_times = last_values[f"-TEMPLATE {day.upper()}-"].replace(" ", "").split(",")
        old_times = template[last_values["-WEEK LIST-"][0]][day]
        if new_times != old_times:
            msg = f"Difference: {old_times} -> {new_times}"
            logger.info(msg)
            difference_found = True
            break
    if difference_found:
        if (
            sg.PopupOKCancel(
                f"Do you wish to save changes for this week? There are currently unsaved changes:\n{msg}"
            )
            != "OK"
        ):
            return
        handle_template_save(last_values, template)


def create_remove_vols_shifts_window(vol: Volunteer):
    sg.set_options(
        suppress_raise_key_errors=False,
        suppress_error_popups=False,
        suppress_key_guessing=False,
    )
    sg.theme("Dark Blue 3")
    today = pendulum.today().format("DD.MM.YY")
    # TODO add Hours of Need

    layout = [
        [sg.T(f"Remove {vol.name} between dates:")],
        [
            sg.T("Remove from (dd.mm.yy)"),
            sg.I(default_text=today, k="-REMOVE VOL START-", s=15),
        ],
        [sg.T("Remove until (dd.mm.yy)"), sg.I(k="-REMOVE VOL END-", s=15)],
        [
            sg.T("Remove from shift types:"),
            sg.InputCombo(
                ("(Duty Room)", "(Leader)", "Both"),
                size=10,
                default_value="Both",
                key="-REMOVE VOL TYPE-",
            ),
        ],
        [sg.B("Remove"), sg.B("Cancel")],
    ]

    window = sg.Window("Remove Signups", layout=layout, finalize=True)
    return window


def handle_remove_vol(session, vol: Volunteer, values) -> int:
    start_dt = pendulum.from_format(values["-REMOVE VOL START-"], "DD.MM.YY")
    end_dt = pendulum.from_format(values["-REMOVE VOL END-"], "DD.MM.YY")
    shift_types = [values["-REMOVE VOL TYPE-"]]
    # TODO add Hours of Need
    if shift_types == ["Both"]:
        shift_types = ["(Duty Room)", "(Leader)", "(Hours of Need)"]
    num = remove_all_sign_ups(session, vol, start_dt, end_dt, shift_types)
    return num


def validate_input(values):
    for i, value in enumerate(values):
        for j, shift in enumerate(value):
            if shift.lower() in ["off", "skip", ""]:
                values[i][j] = "OFF"
                continue
            if "-" not in shift:
                sg.popup(
                    f"invalid input in week {i + 1}, correct syntax is Monday 1500-1800, found: \n{shift}\tHyphen needed between times.",
                    keep_on_top=True,
                )
                return False
            try:
                pendulum.from_format(shift.strip().split("-")[0], "dddd HHmm")
                pendulum.from_format(shift.split("-")[1], "HHmm")
            except ValueError:
                sg.popup(
                    f"invalid input in week{i + 1}, correct syntax is Monday 1500-1800, found: \n{shift}",
                    keep_on_top=True,
                )
                return False
    return values


if __name__ == "__main__":
    s = requests.Session()
    s.auth = (f"{login_info['username']}", f"{login_info['password']}")
    main_window(s)
    # assign_rota(s)
    # reformat_rota()
    # if sys.platform == "win32":
    #     asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # rota = load_rota_template()
    # shifts = rota_pattern_to_dates(s, rota, pendulum.today(), rota_length=2)
    # for shif in shifts:
    #     print(shif.format("DD.MM.YY @ HHmm (dddd)"))
