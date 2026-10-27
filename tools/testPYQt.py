97
98
99
100
101
102
103
104
105
106
107
108
109
110
111
112
113
114
115
116
117
118
119
120
121
122
123
124
125
126
127
128
129
130
131
132
133
134
135
136
137
138
139
140
141
142
143
144
145
146
147
148
149
150
151
152
153
154
155
156
157
158
159
160
161
162
163
164
165
166
167
168
169
170
171
172
173
174
175
176
177
178
179
180
181
182
183
184
185
186
187
188
189
190
191
192
193
194
195
196
197
198
199
200
201
202
203
204
205
206
207
208
209
210
211
212
213
214
215
216
217
218
219
220
221
222
223
224
                           relief="flat", bd=0, bg=PANEL, fg=MUTED,
                           activebackground=PANEL2, activeforeground=TEXT,
                           cursor="hand2", pady=12)
        button.pack(fill="x", padx=9, pady=2)
        nav_buttons[name] = button

    tk.Label(sidebar, text="NUR TEST · KEINE BERECHNUNG", bg=PANEL,
             fg=GREEN, font=("Segoe UI", 8, "bold")).pack(
                 side="bottom", pady=23)

    header = tk.Frame(content, bg=BG)
    header.pack(fill="x", padx=30, pady=(26, 7))
    tk.Label(header, textvariable=title_var, bg=BG, fg=TEXT,
             font=("Segoe UI", 23, "bold")).pack(side="left")
    tk.Label(header, text="●  " + check_powerfactory(), bg=BG,
             fg=GREEN, font=("Segoe UI", 10)).pack(side="right")
    tk.Label(content, textvariable=subtitle_var, bg=BG, fg=MUTED,
             font=("Segoe UI", 10), anchor="w").pack(fill="x", padx=31, pady=(0, 14))

    # Die Seiten befinden sich unter einem dauerhaft sichtbaren Kopfbereich.
    body = tk.Frame(content, bg=BG)
    body.pack(fill="both", expand=True, padx=30, pady=(0, 25))
    # Alle Seiten liegen im gemeinsamen Body-Bereich.
    pages = {name: tk.Frame(body, bg=BG) for name, _ in nav_spec}

    def label(parent, text, size=11, bold=False, fg=TEXT):
        return tk.Label(parent, text=text, bg=BG, fg=fg, anchor="w",
                        font=("Segoe UI", size, "bold" if bold else "normal"))

    home = pages["Übersicht"]
    label(home, "Test-Komponenten", 12, True).pack(anchor="w", pady=(8, 10))
    card = tk.Canvas(home, height=118, bg=BG, highlightthickness=0)
    card.pack(fill="x", pady=(0, 18))

    def draw_card(event=None):
        card.delete("all")
        width = max(320, card.winfo_width())
        rounded_rect(card, 2, 2, width - 2, 116, 18, PANEL2)
        card.create_text(24, 30, text="GUI-Kompatibilität", anchor="w",
                         font=("Segoe UI", 12, "bold"), fill=TEXT)
        card.create_text(24, 69, text="Canvas  ·  ttk  ·  native Python  ·  kein Webserver",
                         anchor="w", font=("Segoe UI", 11), fill=MUTED)
        card.create_oval(width - 49, 43, width - 27, 65,
                         fill=GREEN, outline="")

    card.bind("<Configure>", draw_card)
    label(home, "Wenn du dieses Fenster siehst, funktioniert tkinter in deiner Python-Umgebung.",
          10, fg=MUTED).pack(anchor="w", pady=(2, 16))

    test_text = tk.StringVar(value="Testfall 2030")
    form = tk.Frame(home, bg=BG)
    form.pack(fill="x", pady=5)
    label(form, "Name des Testfalls", 10).pack(anchor="w", pady=(0, 5))
    entry = ttk.Entry(form, textvariable=test_text, width=38, font=("Segoe UI", 11))
    entry.pack(anchor="w", pady=(0, 12))

    assessment_n0 = tk.BooleanVar(value=True)
    assessment_n1 = tk.BooleanVar(value=True)
    checks = tk.Frame(home, bg=BG)
    checks.pack(anchor="w")
    tk.Checkbutton(checks, text="n-0", variable=assessment_n0, bg=BG,
                   fg=TEXT, selectcolor=PANEL, activebackground=BG,
                   activeforeground=TEXT).pack(side="left", padx=(0, 22))
    tk.Checkbutton(checks, text="n-1", variable=assessment_n1, bg=BG,
                   fg=TEXT, selectcolor=PANEL, activebackground=BG,
                   activeforeground=TEXT).pack(side="left")

    def test_button():
        messagebox.showinfo(
            "GridLens GUI-Test erfolgreich",
            "Dialog funktioniert.\n\nTestfall: {}\nn-0: {}\nn-1: {}\n\n"
            "Es wurde keine PowerFactory-Berechnung ausgeführt.".format(
                test_text.get(), assessment_n0.get(), assessment_n1.get()),
            parent=root)

    controls = tk.Frame(home, bg=BG)
    controls.pack(anchor="w", pady=22)
    tk.Button(controls, text="Oberfläche testen", command=test_button,
              bg=ACCENT, fg="white", activebackground="#2563eb",
              activeforeground="white", font=("Segoe UI", 11, "bold"),
              padx=19, pady=11, bd=0, relief="flat",
              cursor="hand2").pack(side="left")
    tk.Button(controls, text="Fenster schließen", command=root.destroy,
              bg=PANEL2, fg=TEXT, activebackground=BORDER,
              activeforeground=TEXT, font=("Segoe UI", 10),
              padx=18, pady=11, bd=0, relief="flat",
              cursor="hand2").pack(side="left", padx=12)

    cases = pages["Planungsfälle"]
    label(cases, "Beispiel-Tabelle (keine echten Netzdaten)", 12, True).pack(
        anchor="w", pady=(8, 14))
    columns = ("fall", "status", "bewertung")
    table = ttk.Treeview(cases, columns=columns, show="headings", style="GL.Treeview")
    for col, title, width in [("fall", "Planungsfall", 240),
                              ("status", "Status", 130),
                              ("bewertung", "Bewertung", 140)]:
        table.heading(col, text=title)
        table.column(col, width=width, anchor="w")
    for item in [("Referenz", "Bereit", "n-0"),
                 ("Kabeltausch Nord", "Entwurf", "n-1"),
                 ("Wartung Trafo 2", "Entwurf", "(n-1)'")]:
        table.insert("", "end", values=item)
    table.pack(fill="both", expand=True)

    net = pages["Netzauswahl"]
    label(net, "Beispiel-Netzauswahl", 12, True).pack(anchor="w", pady=(8, 15))
    selected_grid = tk.StringVar(value="Gesamtes Netz")
    ttk.Combobox(net, textvariable=selected_grid, state="readonly", width=35,
                 values=("Gesamtes Netz", "Netz Nord", "Netz Süd")).pack(anchor="w")
    label(net, "Nur Demo-Werte. Es werden keine PowerFactory-Netze gelesen.",
          10, fg=MUTED).pack(anchor="w", pady=14)

    settings = pages["Einstellungen"]
    label(settings, "Darstellung", 12, True).pack(anchor="w", pady=(8, 15))
    label(settings, "Dieses Beispiel nutzt tkinter, ttk und Canvas.",
          11, fg=MUTED).pack(anchor="w")
    label(settings, "Keine Installation und kein zusätzlicher Dienst erforderlich.",
          11, fg=MUTED).pack(anchor="w", pady=8)

    show_page("Übersicht")
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    try:
        root.mainloop()
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass