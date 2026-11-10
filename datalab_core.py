import flet as ft
import pandas as pd
import json
import io
import traceback
import sys
from datetime import datetime
from pathlib import Path
import difflib

# Syntax highlighting
try:
    import flet_code_editor as fce
    HAS_CODE_EDITOR = True
except ImportError:
    HAS_CODE_EDITOR = False
    print("Tip: install syntax highlighting with →  pip install flet-code-editor")

class DataWorkbench:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "CSV / JSON Data Workbench + Python Interpreter"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.padding = 15

        self.original_df: pd.DataFrame | None = None
        self.df: pd.DataFrame | None = None
        self.current_file: str | None = None
        self.code_font_size = 14

        # FilePicker is a Service
        self.file_picker = ft.FilePicker()
        self.page.services.append(self.file_picker)

        # Status bar
        self.status = ft.Text("No file loaded", color=ft.Colors.GREY_400, size=13)

        # Data table area
        self.table_container = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO)

        # Output / Diff console
        self.output = ft.TextField(
            label="Output / Diff",
            multiline=True,
            min_lines=12,
            max_lines=20,
            read_only=True,
            text_style=ft.TextStyle(font_family="Consolas", size=13),
            expand=True,
        )

        # Font size label
        self.code_font_label = ft.Text(f"Font: {self.code_font_size}", size=12)

        # Code editor
        if HAS_CODE_EDITOR:
            self.code_editor = fce.CodeEditor(
                value=self.get_template_code(),
                language=fce.CodeLanguage.PYTHON,
                code_theme=fce.CodeTheme.ATOM_ONE_DARK,
                expand=True,
                text_style=ft.TextStyle(font_family="Consolas", size=self.code_font_size),
            )
        else:
            self.code_editor = ft.TextField(
                value=self.get_template_code(),
                multiline=True,
                min_lines=12,
                max_lines=18,
                text_style=ft.TextStyle(font_family="Consolas", size=self.code_font_size),
                expand=True,
            )

        self.build_ui()

    def get_template_code(self) -> str:
        return '''# df is already loaded as a pandas DataFrame
# Available: pd, datetime, Path, etc.

def parse_date(row):
    """Parse Date_Added according to the Source locale."""
    date_str = str(row["Date_Added"]).strip().replace(" ", "")
    source = str(row["Source"]).lower()

    try:
        if "us mac" in source:
            for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y"):
                try:
                    return datetime.strptime(date_str, fmt).date()
                except ValueError:
                    continue
        elif "nl laptop" in source:
            for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y"):
                try:
                    return datetime.strptime(date_str, fmt).date()
                except ValueError:
                    continue
        else:  # Server / ISO
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d"):
                try:
                    return datetime.strptime(date_str, fmt).date()
                except ValueError:
                    continue
    except Exception:
        pass
    return None

df["Date_Parsed"] = df.apply(parse_date, axis=1)

print("Date parsing done. New column 'Date_Parsed' added.")
print(df[["Filename", "Date_Added", "Source", "Date_Parsed"]].head(10))
'''

    def change_font_size(self, delta: int):
        self.code_font_size = max(10, min(28, self.code_font_size + delta))
        self.code_font_label.value = f"Font: {self.code_font_size}"

        new_style = ft.TextStyle(font_family="Consolas", size=self.code_font_size)
        if HAS_CODE_EDITOR:
            self.code_editor.text_style = new_style
        else:
            self.code_editor.text_style = new_style
        self.page.update()

    def build_ui(self):
        # Toolbar
        toolbar = ft.Row(
            [
                ft.Button("Load CSV / JSON", icon=ft.Icons.FOLDER_OPEN, on_click=self.pick_file),
                ft.Button("Run Code", icon=ft.Icons.PLAY_ARROW, bgcolor=ft.Colors.GREEN_700, on_click=self.run_code),
                ft.Button("Show Diff", icon=ft.Icons.COMPARE, on_click=self.show_diff),
                ft.Button("Save Copy", icon=ft.Icons.SAVE, on_click=self.save_copy),
                ft.Button("Reset", icon=ft.Icons.RESTORE, on_click=self.reset_df),
                ft.VerticalDivider(),
                ft.IconButton(ft.Icons.TEXT_DECREASE, tooltip="Smaller font", on_click=lambda e: self.change_font_size(-1)),
                self.code_font_label,
                ft.IconButton(ft.Icons.TEXT_INCREASE, tooltip="Larger font", on_click=lambda e: self.change_font_size(+1)),
            ],
            spacing=8,
        )

        # Left side – full height Data Table
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

        # Right side – Output + Python Interpreter stacked
        right_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Text("Output / Diff", weight=ft.FontWeight.BOLD),
                    self.output,                          # output text area
                    ft.Divider(height=10),
                    ft.Text("Python Interpreter", weight=ft.FontWeight.BOLD),
                    self.code_editor,                     # code editor under the output
                ],
                expand=True,
                spacing=6,
            ),
            expand=2,
            border=ft.Border.all(1, ft.Colors.OUTLINE),
            border_radius=6,
            padding=10,
        )

        # Main content row (table full height)
        main_content = ft.Row(
            [
                left_panel,
                right_panel,
            ],
            expand=True,
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )

        self.page.add(
            toolbar,
            self.status,
            ft.Divider(height=8),
            main_content,          # this now takes all remaining height
        )

    async def pick_file(self, e):
        files = await self.file_picker.pick_files(
            dialog_title="Select CSV or JSON file",
            allowed_extensions=["csv", "json", "txt"],
            allow_multiple=False,
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
            self.output.value = "File loaded successfully. You can now run Python code on `df`."
        except Exception:
            self.output.value = f"Error loading file:\n{traceback.format_exc()}"
        self.page.update()

    def refresh_table(self):
        if self.df is None:
            return

        preview = self.df.head(100)
        columns = [ft.DataColumn(ft.Text(col, weight=ft.FontWeight.BOLD)) for col in preview.columns]
        rows = []
        for _, row in preview.iterrows():
            cells = [ft.DataCell(ft.Text(str(v)[:50])) for v in row]
            rows.append(ft.DataRow(cells=cells))

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

    def run_code(self, e):
        if self.df is None:
            self.output.value = "Load a file first."
            self.page.update()
            return

        code = self.code_editor.value

        old_stdout = io.StringIO()
        sys_stdout = sys.stdout
        sys.stdout = old_stdout

        local_ns = {
            "df": self.df,
            "pd": pd,
            "datetime": datetime,
            "Path": Path,
            "original_df": self.original_df,
        }

        try:
            exec(code, {"__builtins__": __builtins__}, local_ns)
            if "df" in local_ns:
                self.df = local_ns["df"]
            self.refresh_table()
            printed = old_stdout.getvalue()
            self.output.value = printed + "\n\n--- Code finished successfully ---"
        except Exception:
            self.output.value = old_stdout.getvalue() + "\n\n" + traceback.format_exc()
        finally:
            sys.stdout = sys_stdout
        self.page.update()

    def show_diff(self, e):
        if self.df is None or self.original_df is None:
            return
        try:
            orig = self.original_df.to_csv(index=False)
            curr = self.df.to_csv(index=False)
            diff = difflib.unified_diff(
                orig.splitlines(), curr.splitlines(),
                fromfile="original", tofile="current", lineterm=""
            )
            diff_text = "\n".join(diff)
            self.output.value = diff_text if diff_text.strip() else "No differences found."
        except Exception as ex:
            self.output.value = f"Diff error: {ex}"
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