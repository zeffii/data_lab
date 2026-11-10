import flet as ft
import pandas as pd
import json
import io
import traceback
import sys
import textwrap
from datetime import datetime
from pathlib import Path
import difflib

try:
    import flet_code_editor as fce
    HAS_CODE_EDITOR = True
except ImportError:
    HAS_CODE_EDITOR = False
    print("Tip: pip install flet-code-editor")

class DataWorkbench:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "CSV / JSON Data Workbench + Python Interpreter"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.padding = 12

        self.original_df = None
        self.df = None
        self.current_file = None
        self.code_font_size = 14
        self.tabs = []
        self.active_tab_index = 0

        # FilePicker
        self.file_picker = ft.FilePicker()
        self.page.services.append(self.file_picker)

        self.status = ft.Text("No file loaded", color=ft.Colors.GREY_400, size=13)
        self.table_container = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO)

        self.output = ft.TextField(
            multiline=True,
            min_lines=7,
            max_lines=10,
            read_only=True,
            text_style=ft.TextStyle(font_family="Consolas", size=13),
            expand=True,
        )

        self.code_font_label = ft.Text(f"Font: {self.code_font_size}", size=12)

        self.build_ui()
        self.add_new_tab("Date Parser", self.get_template_code())

    def get_template_code(self) -> str:
        return textwrap.dedent('''
            # Correct date parser for your sample file
            def parse_date(row):
                # We must import inside the function because names injected
                # into exec() are not visible inside nested functions.
                from datetime import datetime as dt

                date_str = str(row["Date_Added"]).strip()
                source = str(row["Source"]).strip().lower()

                if "us mac" in source:
                    formats = ["%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y"]
                elif "nl laptop" in source:
                    formats = ["%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y"]
                else:  # Server
                    formats = ["%Y-%m-%d", "%Y/%m/%d"]

                for fmt in formats:
                    try:
                        return dt.strptime(date_str, fmt).date()
                    except ValueError:
                        continue
                return None

            df["Date_Parsed"] = df.apply(parse_date, axis=1)

            print("Parsing complete!")
            print(df[["Filename", "Date_Added", "Source", "Date_Parsed"]].head(12).to_string())
            print("\\nSuccess:", df["Date_Parsed"].notna().sum(), "/", len(df))
        ''').strip()

    def change_font_size(self, delta: int):
        self.code_font_size = max(10, min(28, self.code_font_size + delta))
        self.code_font_label.value = f"Font: {self.code_font_size}"
        for tab in self.tabs:
            tab["editor"].text_style = ft.TextStyle(font_family="Consolas", size=self.code_font_size)
        self.page.update()

    def create_editor(self, content: str):
        if HAS_CODE_EDITOR:
            return fce.CodeEditor(
                value=content,
                language=fce.CodeLanguage.PYTHON,
                code_theme=fce.CodeTheme.ATOM_ONE_DARK,
                expand=True,
                text_style=ft.TextStyle(font_family="Consolas", size=self.code_font_size),
            )
        else:
            return ft.TextField(
                value=content,
                multiline=True,
                min_lines=10,
                max_lines=15,
                text_style=ft.TextStyle(font_family="Consolas", size=self.code_font_size),
                expand=True,
            )

    def add_new_tab(self, name: str = None, content: str = "# New script\\n"):
        if name is None:
            name = f"Script {len(self.tabs) + 1}"
        editor = self.create_editor(content)
        self.tabs.append({"name": name, "editor": editor})
        self.active_tab_index = len(self.tabs) - 1
        self.refresh_tabs_ui()

    def close_tab(self, index: int):
        if len(self.tabs) <= 1:
            return
        self.tabs.pop(index)
        if self.active_tab_index >= len(self.tabs):
            self.active_tab_index = len(self.tabs) - 1
        self.refresh_tabs_ui()

    def switch_tab(self, index: int):
        self.active_tab_index = index
        self.refresh_tabs_ui()

    def refresh_tabs_ui(self):
        tab_buttons = []
        for i, tab in enumerate(self.tabs):
            is_active = (i == self.active_tab_index)
            tab_buttons.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Text(tab["name"], size=13,
                                    weight=ft.FontWeight.BOLD if is_active else None),
                            ft.IconButton(
                                icon=ft.Icons.CLOSE,
                                icon_size=14,
                                on_click=lambda e, idx=i: self.close_tab(idx),
                                tooltip="Close tab",
                            ) if len(self.tabs) > 1 else ft.Container(width=0),
                        ],
                        spacing=4,
                        tight=True,
                    ),
                    padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST if is_active else None,
                    border_radius=6,
                    on_click=lambda e, idx=i: self.switch_tab(idx),
                )
            )

        tab_buttons.append(
            ft.IconButton(
                icon=ft.Icons.ADD,
                tooltip="New tab",
                on_click=lambda e: self.add_new_tab(),
            )
        )

        self.tabs_row.controls = tab_buttons
        self.editor_container.content = self.tabs[self.active_tab_index]["editor"]
        self.page.update()

    def build_ui(self):
        # Top toolbar
        toolbar = ft.Row(
            [
                ft.Button("Load CSV / JSON", icon=ft.Icons.FOLDER_OPEN, on_click=self.pick_file),
                ft.Button("Show Diff", icon=ft.Icons.COMPARE, on_click=self.show_diff),
                ft.Button("Save Copy", icon=ft.Icons.SAVE, on_click=self.save_copy),
                ft.Button("Reset", icon=ft.Icons.RESTORE, on_click=self.reset_df),
                ft.VerticalDivider(),
                ft.IconButton(ft.Icons.TEXT_DECREASE, on_click=lambda e: self.change_font_size(-1)),
                self.code_font_label,
                ft.IconButton(ft.Icons.TEXT_INCREASE, on_click=lambda e: self.change_font_size(+1)),
            ],
            spacing=8,
        )

        # Left panel – full height table
        left_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Text("Data Preview", weight=ft.FontWeight.BOLD),
                    self.table_container,
                ],
                expand=True,
            ),
            expand=3,
            border=ft.Border.all(1, ft.Colors.OUTLINE),
            border_radius=6,
            padding=10,
        )

        # Right panel
        self.tabs_row = ft.Row(scroll=ft.ScrollMode.AUTO) #, expand=True)
        self.editor_container = ft.Container(expand=True)

        run_button = ft.Button(
            "Run Code",
            icon=ft.Icons.PLAY_ARROW,
            bgcolor=ft.Colors.GREEN_700,
            on_click=self.run_current_code,
        )

        right_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Text("Output / Diff", weight=ft.FontWeight.BOLD),
                    self.output,
                    ft.Divider(height=8),
                    
                    # Header row with title + Run button
                    ft.Row(
                        [
                            ft.Text("Python Interpreter", weight=ft.FontWeight.BOLD),
                            run_button,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    
                    # Tabs – compact height
                    self.tabs_row,
                    
                    # Code editor takes the remaining space
                    self.editor_container,
                ],
                expand=True,
                spacing=6,
            ),
            expand=2,
            border=ft.Border.all(1, ft.Colors.OUTLINE),
            border_radius=6,
            padding=10,
        )

        main_content = ft.Row(
            [left_panel, right_panel],
            expand=True,
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )

        self.page.add(
            toolbar,
            self.status,
            ft.Divider(height=6),
            main_content,
        )

    async def pick_file(self, e):
        files = await self.file_picker.pick_files(
            allowed_extensions=["csv", "json", "txt"],
            dialog_title="Select CSV or JSON file",
        )
        if not files:
            return

        path = files[0].path
        self.current_file = path

        try:
            if path.lower().endswith(".json"):
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                self.df = pd.json_normalize(data) if isinstance(data, list) else pd.DataFrame([data])
            else:
                try:
                    self.df = pd.read_csv(path, sep=";", dtype=str, keep_default_na=False)
                except Exception:
                    self.df = pd.read_csv(path, dtype=str, keep_default_na=False)

            self.original_df = self.df.copy(deep=True)
            self.status.value = f"Loaded: {Path(path).name}  →  {len(self.df)} rows × {len(self.df.columns)} columns"
            self.refresh_table()
            self.output.value = "File loaded successfully."
        except Exception:
            self.output.value = traceback.format_exc()
        self.page.update()

    def refresh_table(self):
        if self.df is None:
            return
        preview = self.df.head(100)
        columns = [ft.DataColumn(ft.Text(c, weight=ft.FontWeight.BOLD)) for c in preview.columns]
        rows = [
            ft.DataRow(cells=[ft.DataCell(ft.Text(str(v)[:50])) for v in row])
            for _, row in preview.iterrows()
        ]
        table = ft.DataTable(
            columns=columns,
            rows=rows,
            border=ft.Border.all(1, ft.Colors.OUTLINE),
            vertical_lines=ft.BorderSide(1, ft.Colors.OUTLINE),
            horizontal_lines=ft.BorderSide(1, ft.Colors.OUTLINE),
            heading_row_color=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        )
        self.table_container.controls = [table]
        self.page.update()

    def run_current_code(self, e):
        if self.df is None:
            self.output.value = "Load a file first."
            self.page.update()
            return

        code = self.tabs[self.active_tab_index]["editor"].value

        old_stdout = io.StringIO()
        sys_stdout = sys.stdout
        sys.stdout = old_stdout

        local_ns = {
            "df": self.df,
            "pd": pd,
            "datetime": datetime,       # important
            "Path": Path,
            "original_df": self.original_df,
        }

        try:
            exec(code, {"__builtins__": __builtins__}, local_ns)
            if "df" in local_ns:
                self.df = local_ns["df"]
            self.refresh_table()
            self.output.value = old_stdout.getvalue() + "\n\n--- Finished successfully ---"
        except Exception:
            self.output.value = old_stdout.getvalue() + "\n\n" + traceback.format_exc()
        finally:
            sys.stdout = sys_stdout
        self.page.update()

    def show_diff(self, e):
        if self.df is None or self.original_df is None:
            return
        orig = self.original_df.to_csv(index=False)
        curr = self.df.to_csv(index=False)
        diff = difflib.unified_diff(orig.splitlines(), curr.splitlines(),
                                    fromfile="original", tofile="current", lineterm="")
        self.output.value = "\n".join(diff) or "No differences."
        self.page.update()

    def save_copy(self, e):
        if self.df is None or not self.current_file:
            return
        p = Path(self.current_file)
        out_path = p.with_name(p.stem + "_edited" + p.suffix)
        try:
            if out_path.suffix.lower() == ".json":
                self.df.to_json(out_path, orient="records", indent=2, force_ascii=False)
            else:
                self.df.to_csv(out_path, index=False, sep=";")
            self.output.value = f"Saved copy to:\n{out_path}"
        except Exception as ex:
            self.output.value = f"Save failed: {ex}"
        self.page.update()

    def reset_df(self, e):
        if self.original_df is not None:
            self.df = self.original_df.copy(deep=True)
            self.refresh_table()
            self.output.value = "Reset to original data."
            self.page.update()

def main(page: ft.Page):
    DataWorkbench(page)

if __name__ == "__main__":
    ft.run(main)