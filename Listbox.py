from random import randint
import FreeSimpleGUI as sg


class Listbox(sg.Listbox):
    def append(self, item):
        self.Widget.insert(sg.tk.END, item)
        self.Values = list(self.Widget.get(0, sg.tk.END))

    def extend(self, items):
        self.Widget.insert(sg.tk.END, *items)
        self.Values = list(self.Widget.get(0, sg.tk.END))

    def insert(self, index, *item):
        self.Widget.insert(index, *item)
        self.Values = list(self.Widget.get(0, sg.tk.END))

    def remove(self, value):
        index = self.index(value)
        if index is not None:
            self.Widget.delete(index)
            self.Values = list(self.Widget.get(0, sg.tk.END))

    def pop(self, i=sg.tk.END):
        widget = self.Widget
        last = widget.index(sg.tk.END)
        if isinstance(i, int) and (i >= last or i < 0):
            i = sg.tk.END
        item = widget.get(i)
        widget.delete(i)
        self.Values = list(self.Widget.get(0, sg.tk.END))
        return item

    def clear(self):
        self.Widget.delete(0, sg.tk.END)
        self.Values = list(self.Widget.get(0, sg.tk.END))

    def index(self, value, start=0, end=sg.tk.END):
        widget = self.Widget
        last = widget.index(sg.tk.END)
        while start < last:
            if widget.get(start) == value:
                return start
            start += 1
        return None

    def sort(self, key=None, reverse=False):
        lst = list(self.Widget.get(0, sg.tk.END))
        lst.sort(key=key, reverse=reverse)
        self.clear()
        self.insert(0, *lst)
        self.Values = list(self.Widget.get(0, sg.tk.END))

    def reverse(self):
        lst = list(self.Widget.get(0, sg.tk.END))
        lst.sort(reverse=True)
        self.clear()
        self.insert(0, *lst)
        self.Values = list(self.Widget.get(0, sg.tk.END))

    def item(self, i, value=None, bg=None, fg=None, bg_selected=None, fg_selected=None):
        widget = self.Widget
        last = widget.index(sg.tk.END)
        if i >= last:
            return
        if value is not None:
            widget.delete(i)
            widget.insert(i, value)
        widget.itemconfig(
            i,
            background=bg,
            foreground=fg,
            selectbackground=bg_selected,
            selectforeground=fg_selected,
        )
        self.Values = list(self.Widget.get(0, sg.tk.END))


# lst = [randint(0, 99) for i in range(10)]

# layout = [[Listbox(lst, size=(10, 10), no_scrollbar=True, key='LISTBOX')]]

# window = sg.Window('Listbox', layout, finalize=True)
# listbox = window['LISTBOX']

# settings = [
#     (3, 'Red',   'red',   'white'),
#     (4, 'Green', 'green', 'white'),
#     (5, 'Blue',  'blue',  'white'),
# ]

# for i, v, bg, fg in settings:
#     listbox.item(i, value=v, bg=bg, fg=fg)

# while True:
#     event, values = window.read()
#     if event in (sg.WINDOW_CLOSED, 'Exit'):
#         break
#     print(event, values)
# window.close()
