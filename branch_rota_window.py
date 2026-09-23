import FreeSimpleGUI as sg
from typing import List

days_of_week = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def col_maker(rota: dict, week_num: int, day: str):
    day_dict = rota[f"Week {week_num}"][day]
    # print(day_dict)
    # print("***")
    a = [[sg.T(day, font="_ 14", justification="center")]]
    for k, v in day_dict.items():
        names = ", ".join([x.name for x in v])
        bg_colour = "orange" if (not names or len(v) != 2) else None
        a.append([sg.T(k, font="_ 12", justification="center")])
        a.append([sg.T(names, font="_ 10", background_color=bg_colour)])
        a.append([sg.T(f"{'-' * len(names)}")])
    return a


## Function to return list containing number of vols on fixed rota each week, to be displayed in tab titles
def rota_counter(rota: dict) -> List[int]:
    rota_count = []
    # rota is dict of 8 weeks.. {"Week 1": {"Monday": {"1900-2200": [Volunteer]}}}
    for week in rota:
        week_counter = 0
        for day in rota[week]:
            day_counter = 0  # unused for now, only looking weekly
            for shift in rota[week][day]:
                day_counter += len(rota[week][day][shift])
                week_counter += len(rota[week][day][shift])
        rota_count.append(week_counter)
    return rota_count


def create_branch_rota_window(rota: dict):
    sg.set_options(
        suppress_raise_key_errors=False,
        suppress_error_popups=False,
        suppress_key_guessing=False,
    )
    sg.theme("Dark Blue 3")
    rota_count = rota_counter(rota)

    week1_tab = [
        [
            sg.Pane(
                [
                    sg.Col(
                        col_maker(rota, 1, day),
                        justification="center",
                        element_justification="center",
                    )
                    for day in days_of_week
                ],
                orientation="h",
                show_handle=False,
                pad=2,
                relief="flat",
            )
        ]
    ]
    week2_tab = [
        [
            sg.Pane(
                [
                    sg.Col(
                        col_maker(rota, 2, day),
                        justification="center",
                        element_justification="center",
                    )
                    for day in days_of_week
                ],
                orientation="h",
                show_handle=False,
                pad=2,
                relief="flat",
            )
        ]
    ]
    week3_tab = [
        [
            sg.Pane(
                [
                    sg.Col(
                        col_maker(rota, 3, day),
                        justification="center",
                        element_justification="center",
                    )
                    for day in days_of_week
                ],
                orientation="h",
                show_handle=False,
                pad=2,
                relief="flat",
            )
        ]
    ]
    week4_tab = [
        [
            sg.Pane(
                [
                    sg.Col(
                        col_maker(rota, 4, day),
                        justification="center",
                        element_justification="center",
                    )
                    for day in days_of_week
                ],
                orientation="h",
                show_handle=False,
                pad=2,
                relief="flat",
            )
        ]
    ]
    week5_tab = [
        [
            sg.Pane(
                [
                    sg.Col(
                        col_maker(rota, 5, day),
                        justification="center",
                        element_justification="center",
                    )
                    for day in days_of_week
                ],
                orientation="h",
                show_handle=False,
                pad=2,
                relief="flat",
            )
        ]
    ]
    week6_tab = [
        [
            sg.Pane(
                [
                    sg.Col(
                        col_maker(rota, 6, day),
                        justification="center",
                        element_justification="center",
                    )
                    for day in days_of_week
                ],
                orientation="h",
                show_handle=False,
                pad=2,
                relief="flat",
            )
        ]
    ]
    week7_tab = [
        [
            sg.Pane(
                [
                    sg.Col(
                        col_maker(rota, 7, day),
                        justification="center",
                        element_justification="center",
                    )
                    for day in days_of_week
                ],
                orientation="h",
                show_handle=False,
                pad=2,
                relief="flat",
            )
        ]
    ]
    week8_tab = [
        [
            sg.Pane(
                [
                    sg.Col(
                        col_maker(rota, 8, day),
                        justification="center",
                        element_justification="center",
                    )
                    for day in days_of_week
                ],
                orientation="h",
                show_handle=False,
                pad=2,
                relief="flat",
            )
        ]
    ]
    layout = [
        [
            sg.TabGroup(
                [
                    [
                        sg.Tab(f"Week 1 ({rota_count[0]})", week1_tab),
                        sg.Tab(f"Week 2 ({rota_count[1]})", week2_tab),
                        sg.Tab(f"Week 3 ({rota_count[2]})", week3_tab),
                        sg.Tab(f"Week 4 ({rota_count[3]})", week4_tab),
                        sg.Tab(f"Week 5 ({rota_count[4]})", week5_tab),
                        sg.Tab(f"Week 6 ({rota_count[5]})", week6_tab),
                        sg.Tab(f"Week 7 ({rota_count[6]})", week7_tab),
                        sg.Tab(f"Week 8 ({rota_count[7]})", week8_tab),
                    ]
                ]
            )
        ]
    ]
    window = sg.Window("Branch Rota", layout=layout, finalize=True)
    return window
