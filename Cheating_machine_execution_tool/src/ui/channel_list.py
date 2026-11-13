"""Flat channel list with independent row spacing and Listbox-style indices."""
from tkinter import END, EventType, Frame, font as tkfont, ttk


class ChannelList(Frame):
    """Adapt the app's existing Listbox calls without changing channel workflows.

    Only native user selection changes emit ``<<ListboxSelect>>``. Treeview also
    emits events for programmatic edits; recording their final selection keeps
    the app's delete/insert/restore refresh from recursively loading a channel.
    """

    def __init__(
        self, master, *, font, background, foreground, selectforeground,
        highlightbackground, highlightcolor, width=34, height=16,
    ):
        self._font = tkfont.Font(master, font=font)
        self._text_height = self._font.metrics('linespace')
        self.row_height = self._text_height + 7
        # Match the original Listbox: 34 character units, 3px text inset and
        # a 1px outer border. Row padding no longer draws a selection bevel.
        pixel_width = width * self._font.measure('0') + 8
        super().__init__(
            master, background=background, borderwidth=0,
            highlightthickness=1, highlightbackground=highlightbackground,
            highlightcolor=highlightcolor, width=pixel_width,
            height=height * self.row_height + 2,
        )
        self.pack_propagate(False)
        self._border_color = highlightbackground
        self._focus_color = highlightcolor
        self._reported_selection = ()
        self._next_item = 0
        self.style_name = f'ChannelList{id(self)}.Treeview'
        style = ttk.Style(self)
        style.configure(
            self.style_name, font=self._font, rowheight=self.row_height,
            background=background, fieldbackground=background,
            foreground=foreground, borderwidth=0, padding=0, indent=0,
        )
        style.map(
            self.style_name,
            background=[('selected', background)],
            foreground=[('selected', selectforeground)],
        )
        # Exclude theme field/focus/indicator/image elements. In particular,
        # Vista's native selection imagery must not reintroduce a blue box.
        style.layout(self.style_name, [('Treeview.treearea', {'sticky': 'nswe'})])
        style.layout(self.style_name + '.Item', [
            ('Treeitem.padding', {'sticky': 'nswe', 'children': [
                ('Treeitem.text', {'sticky': 'nswe'}),
            ]}),
        ])
        style.configure(self.style_name + '.Item', padding=(3, 3, 3, 4))
        self._tree = ttk.Treeview(
            self, show='tree', selectmode='browse', height=height,
            style=self.style_name, takefocus=True,
        )
        self._tree.column('#0', width=pixel_width-2, minwidth=0, stretch=True)
        self._tree.pack(fill='both', expand=True)
        self._tree.bind('<<TreeviewSelect>>', self._on_tree_selection)
        self._tree.bind('<FocusIn>', self._on_focus)
        self._tree.bind('<FocusOut>', self._on_focus)
        self._tree.bind('<Control-Home>', lambda event: self._select_edge(0))
        self._tree.bind('<Control-End>', lambda event: self._select_edge(END))

    def _on_focus(self, event):
        self.configure(highlightbackground=(
            self._focus_color if event.type == EventType.FocusIn else self._border_color
        ))

    def _on_tree_selection(self, _event):
        selected = self.curselection()
        if selected != self._reported_selection:
            self._reported_selection = selected
            self._tree.event_generate('<<ListboxSelect>>')

    def _select_edge(self, index):
        items = self._items()
        if items:
            iid = items[self._index(index)]
            self._tree.selection_set(iid)
            self._tree.focus(iid)
            self._tree.see(iid)
        return 'break'

    def _items(self):
        return self._tree.get_children('')

    def _index(self, index, *, insertion=False):
        size = len(self._items())
        if index == END:
            return size if insertion else size - 1
        return int(index)

    def _record_selection(self):
        self._reported_selection = self.curselection()

    def insert(self, index, *elements):
        position = max(0, min(self._index(index, insertion=True), len(self._items())))
        for text in elements:
            self._next_item += 1
            self._tree.insert('', position, iid=f'channel-row-{self._next_item}', text=text)
            position += 1
        self._record_selection()

    def delete(self, first, last=None):
        items = self._items()
        start = max(0, self._index(first))
        stop = self._index(first if last is None else last) + 1
        removed = items[start:max(start, stop)]
        if removed:
            self._tree.delete(*removed)
        self._record_selection()

    def get(self, first, last=None):
        items = self._items()
        if last is None:
            return self._tree.item(items[self._index(first)], 'text')
        return tuple(self._tree.item(iid, 'text') for iid in items[
            max(0, self._index(first)):self._index(last)+1
        ])

    def curselection(self):
        selected = set(self._tree.selection())
        return tuple(i for i, iid in enumerate(self._items()) if iid in selected)

    def selection_clear(self, first, last=None):
        items = self._items()
        start = max(0, self._index(first))
        stop = self._index(first if last is None else last) + 1
        removed = items[start:max(start, stop)]
        if removed:
            self._tree.selection_remove(*removed)
        self._record_selection()

    def selection_set(self, index):
        items = self._items()
        position = self._index(index)
        if 0 <= position < len(items):
            self._tree.selection_set(items[position])
            self._tree.focus(items[position])
        self._record_selection()

    def nearest(self, y):
        items = self._items()
        if not items:
            return -1
        item = self._tree.identify_row(y)
        if item:
            return items.index(item)
        visible = [(i, self._tree.bbox(iid)) for i, iid in enumerate(items)]
        visible = [(i, box) for i, box in visible if box]
        if not visible:
            return -1
        return min(visible, key=lambda pair: abs(y - (pair[1][1] + self.row_height/2)))[0]

    def bbox(self, index):
        items = self._items()
        position = self._index(index)
        if not 0 <= position < len(items):
            return None
        box = self._tree.bbox(items[position])
        if not box:
            return None
        return (
            box[0]+3, box[1]+3,
            self._font.measure(self._tree.item(items[position], 'text')),
            self._text_height,
        )

    def itemconfig(self, index, **options):
        iid = self._items()[self._index(index)]
        self._tree.tag_configure(iid, **options)
        self._tree.item(iid, tags=(iid,))

    def see(self, index):
        self._tree.see(self._items()[self._index(index)])

    def yview(self, *args):
        return self._tree.yview(*args)

    def bind(self, sequence=None, func=None, add=None):
        return self._tree.bind(sequence, func, add)

    def event_generate(self, sequence, **options):
        return self._tree.event_generate(sequence, **options)

    def focus_set(self):
        return self._tree.focus_set()

    def focus_force(self):
        return self._tree.focus_force()
