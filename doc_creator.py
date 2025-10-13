import json
from docx import Document
from datetime import datetime
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from calendar import month_name
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import RGBColor

class ScheduleDocxCreator:
    def __init__(
        self,
        json_path="output/schedule_output.json",
        doc_path="output/example.docx",
        font_name="Calibri",
        font_size=10,
        header_font_size=24,
        column_widths=None,
        weekend_color="D6E3BC",
        holiday_color="D6E3BC",
        night_shift_labels=None  # NEW: setting for night shift labels
    ):
        self.json_path = json_path
        self.doc_path = doc_path
        self.font_name = font_name
        self.font_size = font_size
        self.header_font_size = header_font_size
        self.weekend_color = weekend_color
        self.holiday_color = holiday_color
        self.night_shift_labels = night_shift_labels or {
            "start": "MONTO NOTTE",
            "end": "SMONTO NOTTE"
        }
        self.column_widths = column_widths or [
            0.2,  # (no title, day/number)
            1.2,  # MATTINO
            1.2,  # POMERIGGIO
            1.2,  # NOTTE
            3.0,  # DESIDERATA
            1.2,  # TIROCINIO/RETE
            1.2   # ASSENZE
        ]
        self.columns = [
            "", "MATTINO", "POMERIGGIO", "NOTTE",
            "DESIDERATA", "TIROCINIO/RETE", "ASSENZE"
        ]
        self.FORBIDDEN_SHIFT_CODES = {
            "afternoon": "NO POME",
            "night": "NO NOTTE",
            "morning": "NO MATT",
        }
        self.DAY_NAME_IT = {
            "Monday": "Lunedì",
            "Tuesday": "Martedì",
            "Wednesday": "Mercoledì",
            "Thursday": "Giovedì",
            "Friday": "Venerdì",
            "Saturday": "Sabato",
            "Sunday": "Domenica",
        }

    def set_row_bg_color(self, row, color_hex):
        for cell in row.cells:
            tc = cell._tc
            tcPr = tc.get_or_add_tcPr()
            shd = OxmlElement('w:shd')
            shd.set(qn('w:fill'), color_hex)
            tcPr.append(shd)

    def get_day_it(self, date_str):
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        day_short = self.DAY_NAME_IT[dt.strftime('%A')][:3].upper()
        return f"{dt.day}\n{day_short}"

    def get_shift_people(self, schedule, people_ids, date_str, shift_type):
        ids = []
        for pid in people_ids:
            shifts = schedule[pid].get(date_str, [])
            if shift_type == "mp":
                if "mp" in shifts:
                    ids.append(pid)
            elif shift_type == "morning":
                if "morning" in shifts or "mp" in shifts:
                    ids.append(pid)
            elif shift_type == "afternoon":
                if "afternoon" in shifts or "mp" in shifts:
                    ids.append(pid)
            else:
                if shift_type in shifts:
                    ids.append(pid)
        return ids

    def get_desiderata(self, date_str, desiderata, people_ids):
        result = []
        for pid in people_ids:
            for entry in desiderata.get(pid, []):
                if entry["date"] == date_str:
                    for s in entry["shifts"]:
                        code = self.FORBIDDEN_SHIFT_CODES.get(s)
                        if code:
                            result.append(f"{pid} ({code})")
        return ", ".join(result)

    def get_internships(self, date_str, tirocinio, people_ids):
        ids = []
        for pid in people_ids:
            if date_str in tirocinio.get(pid, []):
                ids.append(pid)
        return ", ".join(ids)

    def get_absences(self, schedule, people_ids, date_str, night_shift_map=None):
        present = set()
        for pid in people_ids:
            shifts = schedule[pid].get(date_str, [])
            if shifts:
                present.add(pid)
        absentees = [pid for pid in people_ids if pid not in present]
        result = []
        for pid in absentees:
            labels = []
            if night_shift_map:
                if pid in night_shift_map.get("start", []):
                    labels.append(self.night_shift_labels['start'])
                if pid in night_shift_map.get("end", []):
                    labels.append(self.night_shift_labels['end'])
            if labels:
                result.append(f"{pid} ({', '.join(labels)})")
            else:
                result.append(pid)
        return ", ".join(result)

    def create_doc(self):
        # --- LOAD JSON AND PARSE SCHEDULE ---
        with open(self.json_path, encoding="utf-8") as f:
            data = json.load(f)

        schedule = data["schedule"]
        people_ids = sorted(schedule.keys())
        all_dates = set()
        for person_sched in schedule.values():
            all_dates.update(person_sched.keys())
        all_dates = sorted(all_dates)

        # --- AUTOMATIC TITLE FROM DATE RANGE (ITALIAN) ---
        MONTH_NAME_IT = [
            "", "GENNAIO", "FEBBRAIO", "MARZO", "APRILE", "MAGGIO", "GIUGNO",
            "LUGLIO", "AGOSTO", "SETTEMBRE", "OTTOBRE", "NOVEMBRE", "DICEMBRE"
        ]
        if all_dates:
            first_date = datetime.strptime(all_dates[0], "%Y-%m-%d")
            title = f"{MONTH_NAME_IT[first_date.month]} {first_date.year}"
        else:
            title = "SCHEDULE"

        desiderata = data.get("desiderata", {})
        tirocinio = data.get("tirocinio", {})
        holidays = set(data.get("holidays", []))

        doc = Document()
        section = doc.sections[0]
        section.left_margin = Inches(0.5)
        section.right_margin = Inches(0.5)

        # Set default font to Calibri for the whole document
        style = doc.styles['Normal']
        font = style.font
        font.name = self.font_name
        font.size = Pt(self.font_size)
        style.element.rPr.rFonts.set(qn('w:eastAsia'), self.font_name)

        # Add heading to the header, not the main body
        header = section.header
        header_paragraph = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
        header_paragraph.text = title
        header_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = header_paragraph.runs[0] if header_paragraph.runs else header_paragraph.add_run()
        run.font.size = Pt(self.header_font_size)
        run.font.name = self.font_name

        table = doc.add_table(rows=1, cols=len(self.columns))
        table.style = "Table Grid"
        for i, col in enumerate(self.columns):
            table.cell(0, i).text = col
            for paragraph in table.cell(0, i).paragraphs:
                for run in paragraph.runs:
                    run.font.name = self.font_name
                    run.bold = True  # Make header row bold
            table.columns[i].width = Inches(self.column_widths[i])

        # Build night shift map for each date: who is mounting/smonting night
        night_shift_map_by_date = {}
        for i, date_str in enumerate(all_dates):
            night_shift_map_by_date[date_str] = {"start": [], "end": []}
        for pid in people_ids:
            for i, date_str in enumerate(all_dates):
                shifts = schedule[pid].get(date_str, [])
                if "night" in shifts:
                    # Night shift starts on this day (MONTO NOTTE)
                    night_shift_map_by_date[date_str]["start"].append(pid)
                    # Night shift ends next day (SMONTO NOTTE)
                    if i + 1 < len(all_dates):
                        next_date = all_dates[i + 1]
                        night_shift_map_by_date[next_date]["end"].append(pid)

        # Prepare data for night shift absences (MONTO/SMONTO NOTTE)
        night_monto_map = {}  # date_str -> list of people who mount night that day
        night_smonta_map = {} # date_str -> list of people who smont night that day

        all_dates_list = all_dates  # already sorted list of date_str

        # Build maps for each date
        for idx, date_str in enumerate(all_dates_list):
            notte_people = self.get_shift_people(schedule, people_ids, date_str, "night")
            night_monto_map[date_str] = notte_people
            # For each person on night shift today, add them as smonto notte for tomorrow
            if idx + 1 < len(all_dates_list):
                next_date = all_dates_list[idx + 1]
                if next_date not in night_smonta_map:
                    night_smonta_map[next_date] = []
                night_smonta_map[next_date].extend(notte_people)

        for idx, date_str in enumerate(all_dates):
            giorno = self.get_day_it(date_str)
            mattino = ", ".join(self.get_shift_people(schedule, people_ids, date_str, "morning"))
            pomeriggio = ", ".join(self.get_shift_people(schedule, people_ids, date_str, "afternoon"))
            notte_people = self.get_shift_people(schedule, people_ids, date_str, "night")
            notte = ", ".join(notte_people)
            desiderata_cell = self.get_desiderata(date_str, desiderata, people_ids)
            tirocinio_cell = self.get_internships(date_str, tirocinio, people_ids)

            # Build ASSENZE column with MONTO/SMONTO NOTTE logic
            assenze_labels = []
            # Add MONTO NOTTE for people on night shift today
            for pid in night_monto_map.get(date_str, []):
                assenze_labels.append(f"{pid} ({self.night_shift_labels['start']})")
            # Add SMONTO NOTTE for people who smont night today
            for pid in night_smonta_map.get(date_str, []):
                assenze_labels.append(f"{pid} ({self.night_shift_labels['end']})")
            # Add other absentees (people not present in any shift)
            present = set()
            for pid in people_ids:
                shifts = schedule[pid].get(date_str, [])
                if shifts:
                    present.add(pid)
            absentees = [pid for pid in people_ids if pid not in present and pid not in night_monto_map.get(date_str, []) and pid not in night_smonta_map.get(date_str, [])]
            assenze_labels.extend(absentees)
            assenze = ", ".join(assenze_labels)

            cells = [giorno, mattino, pomeriggio, notte, desiderata_cell, tirocinio_cell, assenze]
            tr = table.add_row().cells
            for i, val in enumerate(cells):
                tr[i].text = val
                for paragraph in tr[i].paragraphs:
                    for run in paragraph.runs:
                        run.font.name = self.font_name
                tr[i].width = Inches(self.column_widths[i])
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            if dt.weekday() in (5, 6):
                self.set_row_bg_color(table.rows[-1], self.weekend_color)
            elif date_str in holidays:
                self.set_row_bg_color(table.rows[-1], self.holiday_color)

        doc.save(self.doc_path)
        print(f"{self.doc_path} created.")

        # --- ADD SNIPPET AFTER TABLE ---
        p = doc.add_paragraph()
        # ORARI DI GUARDIA (bold, underline)
        run = p.add_run("\n\nORARI DI GUARDIA: ")
        run.bold = True
        run.underline = True
        p.add_run("\nMattina: 8-14\nPomeriggio: 14-20\nNotte: 20-8\n")
        # LEGENDA (bold, underline)
        run2 = p.add_run("LEGENDA: ")
        run2.bold = True
        run2.underline = True
        p.add_run("\nX turno da 6 ore\n")
        run3 = p.add_run("X")
        run3.underline = True
        p.add_run(" turno da 12 ore\n")
        run4 = p.add_run("COGNOME")
        run4.underline = True
        p.add_run(" Specializzando di guardia\n")
        # COGNOME(*) (lightblue)
        run5 = p.add_run("COGNOME(*)")
        run5.underline = True
        run5.font.color.rgb = RGBColor(0x4A, 0x90, 0xE2)  # light blue
        p.add_run(" Specializzando in recupero\n")
        # COGNOME (green)
        run6 = p.add_run("COGNOME")
        run6.underline = True
        run6.font.color.rgb = RGBColor(0x00, 0x80, 0x00)  # green
        p.add_run(" Monto/smonto notte")

        doc.save(self.doc_path)
        print(f"{self.doc_path} created.")

if __name__ == "__main__":
    # Example usage with custom settings
    creator = ScheduleDocxCreator(
        json_path="output/schedule_output.json",
        doc_path="output/example.docx",
        font_name="Calibri",
        font_size=10,
        header_font_size=24,
        column_widths=[
            0.2, 1.2, 1.2, 1.2, 3.0, 1.2, 1.2
        ],
        weekend_color="D6E3BC",  # RGB 214,227,188
        holiday_color="D6E3BC"
    )
    creator.create_doc()
