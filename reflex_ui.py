import reflex as rx

def shell(*children, title="PIPSGOX", subtitle=""):
    return rx.vstack(
        rx.heading(title, size="7"),
        rx.cond(subtitle != "", rx.text(subtitle, color="gray"), rx.fragment()),
        *children,
        spacing="4", width="100%", max_width="1400px", margin="auto", padding="24px"
    )

def table_from_rows(headers, rows):
    def render_row(row):
        return rx.table.row(*[rx.table.cell(row[h]) for h in headers])
    return rx.table.root(
        rx.table.header(rx.table.row(*[rx.table.column_header_cell(h) for h in headers])),
        rx.table.body(rx.foreach(rows, render_row)),
        width="100%", variant="surface"
    )
