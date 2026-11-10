import flet as ft
import pandas as pd
import json
import io
import traceback
from datetime import datetime
from pathlib import Path
import difflib
from copy import deepcopy

class DataWorkbench:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "CSV / JSON Data Workbench + Python Interpreter"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.padding = 20

        self.original_df: pd.DataFrame | None = None
        self.df: pd.DataFrame | None = None
        self.current_file: str | None = None

        # UI controls
        self.status = ft.Text("No file loaded", color=ft.Colors.GREY_400)
        self.table_container = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO)
        self.code_field = ft.TextField(
            label="Python code (df is the current DataFrame)",
            multiline=True,
            min_lines=12,
            max_lines=20,
            value=self.get_template_code(),
            text_style=ft.TextStyle(font_family="Consolas"),
            expand=True,
        )
        self.output = ft.TextField(
            label="Output / Diff",
            multiline=True,
            min_lines=8,
            max_lines=15,
            read_only=True,
            text_style=ft.TextStyle(font_family="Consolas"),
            expand=True,
        )

        self.file_picker = ft.FilePicker(on_result=self.on_file_picked)
        self.page.overlay.append(self.file_picker)

        self.build_ui()

    def get_template_code(self) -> str:
        return '''# df is already loaded as a pandas DataFrame
# Available: pd, datetime, Path, etc.

def parse_date(row):
    """Parse Date_Added according to the Source locale."""
    date_str = str(row["Date_Added"]).strip()
    source = str(row["Source"]).lower()

    # Clean common noise
    date_str = date_str.replace(" ", "")

    try:
        if "us mac" in source:
            # US: MM/DD/YYYY or MM-DD-YYYY
            for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y"):
                try:
                    return datetime.strptime(date_str, fmt).date()
                except ValueError:
                    continue
        elif "nl laptop" in source:
            # NL/European: DD-MM-YYYY or DD/MM/YYYY
            for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y"):
                try:
                    return datetime.strptime(date_str, fmt).date()
                except ValueError:
                    continue
        else:
            # Server / ISO first, then fallbacks
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d"):
                try:
                    return datetime.strptime(date_str, fmt).date()
                except ValueError:
                    continue
    except Exception:
        pass
    return None   # or pd.NaT

# Apply the parser
df["Date_Parsed"] = df.apply(parse_date, axis=1)

# Optional extras you can uncomment / modify:
# df["Category"] = df["Category"].str.strip().str.title()
# df["BPM"] = df["BPM"].astype(str).str.replace(r"[^0-9]", "", regex=True).replace("", pd.NA).astype("Int64")
# df["Length_s"] = df["Length_s"].astype(str).str.replace(",", ".").astype(float)

print("Date parsing done. New column 'Date_Parsed' added.")
print(df[["Filename", "Date_Added", "Source", "Date_Parsed"]].head(10))
'''

    def build_ui(self):
        self.page.add(
            ft.Row([
                ft.ElevatedButton("Load CSV / JSON", icon=ft.Icons.FOLDER_OPEN,
                                  on_click=lambda _: self.file_picker.pick_files(
                                      allowed_extensions=["csv", "json", "txt"])),
                ft.ElevatedButton("Run Code", icon=ft.Icons.PLAY_ARROW,
                                  bgcolor=ft.Colors.GREEN_700, on_click=self.run_code),
                ft.ElevatedButton("Show Diff", icon=ft.Icons.COMPARE,
                                  on_click=self.show_diff),
                ft.ElevatedButton("Save Copy", icon=ft.Icons.SAVE,
                                  on_click=self.save_copy),
                ft.ElevatedButton("Reset to Original", icon=ft.Icons.RESTORE,
                                  on_click=self.reset_df),
            ]),
            self.status,
            ft.Divider(),
            ft.Text("Data Preview", weight=ft.FontWeight.BOLD),
            self.table_container,
            ft.Divider(),
            ft.Text("Python Interpreter", weight=ft.FontWeight.BOLD),
            self.code_field,
            self.output,
        )

    def on_file_picked(self, e: ft.FilePickerResultEvent):
        if not e.files:
            return
        path = e.files[0].path
        self.current_file = path
        try:
            if path.lower().endswith(".json"):
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                self.df = pd.json_normalize(data) if isinstance(data, list) else pd.DataFrame([data])
            else:
                # Try semicolon first (your sample), then comma
                try:
                    self.df = pd.read_csv(path, sep=";", dtype=str, keep_default_na=False)
                except Exception:
                    self.df = pd.read_csv(path, dtype=str, keep_default_na=False)

            self.original_df = self.df.copy(deep=True)
            self.status.value = f"Loaded: {Path(path).name}  →  {len(self.df)} rows × {len(self.df.columns)} columns"
            self.refresh_table()
            self.output.value = "File loaded successfully. You can now run Python code on `df`."
        except Exception as ex:
            self.output.value = f"Error loading file:\n{traceback.format_exc()}"
        self.page.update()

    def refresh_table(self):
        if self.df is None:
            return
        # Limit preview for performance
        preview = self.df.head(100)
        columns = [ft.DataColumn(ft.Text(col, weight=ft.FontWeight.BOLD)) for col in preview.columns]
        rows = []
        for _, row in preview.iterrows():
            cells = [ft.DataCell(ft.Text(str(v)[:40])) for v in row]
            rows.append(ft.DataRow(cells=cells))

        table = ft.DataTable(
            columns=columns,
            rows=rows,
            border=ft.border.all(1, ft.Colors.OUTLINE),
            vertical_lines=ft.border.BorderSide(1, ft.Colors.OUTLINE),
            horizontal_lines=ft.border.BorderSide(1, ft.Colors.OUTLINE),
            heading_row_color=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        )
        self.table_container.controls = [table]
        self.page.update()

    def run_code(self, e):
        if self.df is None:
            self.output.value = "Load a file first."
            self.page.update()
            return

        # Capture stdout
        old_stdout = io.StringIO()
        import sys
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
            exec(self.code_field.value, {"__builtins__": __builtins__}, local_ns)
            # If user reassigned df, pick it up
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
            # Simple textual diff on the CSV representation
            orig = self.original_df.to_csv(index=False)
            curr = self.df.to_csv(index=False)
            diff = difflib.unified_diff(
                orig.splitlines(), curr.splitlines(),
                fromfile="original", tofile="current", lineterm=""
            )
            diff_text = "\n".join(diff)
            if not diff_text.strip():
                diff_text = "No differences found."
            self.output.value = diff_text
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
    ft.app(target=main)