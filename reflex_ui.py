import reflex as rx

def shell(*children, title="PIPSGOX", subtitle=""):
    return rx.vstack(
        rx.heading(title, size="7"),
        rx.cond(subtitle != "", rx.text(subtitle, color="gray"), rx.fragment()),
        *children,
        spacing="4", width="100%", max_width="1400px", margin="auto", padding="24px"
    )

def table_from_rows(headers, rows):
    return rx.table.root(
        rx.table.header(rx.table.row(*[rx.table.column_header_cell(h) for h in headers])),
        rx.table.body(*[rx.table.row(*[rx.table.cell(str(r.get(h, '—'))) for h in headers]) for r in rows]),
        width="100%", variant="surface"
    )
