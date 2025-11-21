import json
from docx import Document
from datetime import datetime, timedelta
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
        night_shift_labels=None,
        hide_vacation_desiderata=True,
        show_vacations_on_holidays=False,
        extend_weekend_desiderata_to_sunday=False,
        night_shift_color="00AA00",  # color for MONTO/SMONTO NOTTE (default green)
        compact_desiderata_in_richieste_table=False,  # NEW: control desiderata format in richieste table
        show_violations=True,
        show_violation_types=[
            'STAFFUNDERMIN',
            'STAFFOVERMAX',
            'ASSIGNSHIFTOVERMAX',
            'WKHOURSUNDERMIN',
            'WKHOURSOVERMAX',
            'FORBIDDENSHIFT',
            'UNDERSTAFFED',
            'NOSHIFT']
            
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
            2.7,  # DESIDERATA
            1.2,  # TIROCINIO/RETE
            1.5   # ASSENZE
        ]
        self.columns = [
            "", "MATTINO", "POMERIGGIO", "NOTTE",
            "DESIDERATA", "TIROCINIO/RETE", "ASSENZE"
        ]
        self.FORBIDDEN_SHIFT_CODES = {
            "afternoon": "NO POME",
            "night": "NO NOTTE", 
            "morning": "NO MATT",
            "split_mp": "NO SMP",
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
        self.hide_vacation_desiderata = hide_vacation_desiderata
        self.show_vacations_on_holidays = show_vacations_on_holidays
        self.night_shift_color = night_shift_color
        self.compact_desiderata_in_richieste_table = compact_desiderata_in_richieste_table
        self.show_violations = show_violations
        self.show_violation_types = show_violation_types
        self.extend_weekend_desiderata_to_sunday = extend_weekend_desiderata_to_sunday

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
                elif "split_mp" in shifts:
                    ids.append(f"{pid}(spz)")
            elif shift_type == "afternoon":
                if "afternoon" in shifts or "mp" in shifts:
                    ids.append(pid)
                elif "split_mp" in shifts:
                    ids.append(f"{pid}(spz)")
            else:
                if shift_type in shifts:
                    ids.append(pid)
        return ids

    def get_desiderata(self, date_str, desiderata, people_ids, vacation_pids=None):
        result = []
        for pid in people_ids:
            # Skip if hiding desiderata for vacation and person is on vacation
            if self.hide_vacation_desiderata and vacation_pids and pid in vacation_pids:
                continue
            for entry in desiderata.get(pid, []):
                if entry["date"] == date_str:
                    for s in entry["shifts"]:
                        if s == "weekend":
                            result.append(f"{pid} (NO WEEKEND)")
                        else:
                            code = self.FORBIDDEN_SHIFT_CODES.get(s)
                            if code:
                                result.append(f"{pid} ({code})")
                # EXTEND NO WEEKEND TO SUNDAY IF ENABLED
                if self.extend_weekend_desiderata_to_sunday:
                    # If entry is NO WEEKEND and date_str is Sunday, check if Saturday has NO WEEKEND for this pid
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    if dt.weekday() == 6:  # Sunday
                        prev_day = dt - timedelta(days=1)
                        prev_day_str = prev_day.strftime("%Y-%m-%d")
                        for prev_entry in desiderata.get(pid, []):
                            if prev_entry["date"] == prev_day_str and "weekend" in prev_entry.get("shifts", []):
                                result.append(f"{pid} (NO WEEKEND)")
                                break
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

    def compact_tirocinio_ranges(self, tirocinio_days, all_dates, holidays):
        """
        Given a list of tirocinio days (YYYY-MM-DD), compact into ranges,
        including weekends/holidays that are surrounded by tirocinio days.
        Returns a string like "3-28" if all days are covered (including surrounded weekends/holidays).
        """
        if not tirocinio_days:
            return "-"
        # Convert to set of date objects for fast lookup
        tirocinio_set = set(datetime.strptime(d, "%Y-%m-%d").date() for d in tirocinio_days)
        all_dates_dt = [datetime.strptime(d, "%Y-%m-%d").date() for d in all_dates]
        holidays_set = set(datetime.strptime(d, "%Y-%m-%d").date() for d in holidays)
        # Build a list of booleans: True if tirocinio, False otherwise
        is_tirocinio = [dt in tirocinio_set for dt in all_dates_dt]
        # Repeat until stable: mark weekends/holidays as tirocinio if surrounded by tirocinio days
        changed = True
        while changed:
            changed = False
            for i, dt in enumerate(all_dates_dt):
                if not is_tirocinio[i]:
                    is_weekend_or_holiday = dt.weekday() >= 5 or dt in holidays_set
                    if is_weekend_or_holiday:
                        # Find previous tirocinio day
                        prev_idx = i - 1
                        while prev_idx >= 0 and (all_dates_dt[prev_idx].weekday() >= 5 or all_dates_dt[prev_idx] in holidays_set):
                            prev_idx -= 1
                        # Find next tirocinio day
                        next_idx = i + 1
                        while next_idx < len(all_dates_dt) and (all_dates_dt[next_idx].weekday() >= 5 or all_dates_dt[next_idx] in holidays_set):
                            next_idx += 1
                        if prev_idx >= 0 and next_idx < len(all_dates_dt):
                            if is_tirocinio[prev_idx] and is_tirocinio[next_idx]:
                                is_tirocinio[i] = True
                                changed = True
        # Now compact consecutive True into ranges
        ranges = []
        i = 0
        while i < len(all_dates_dt):
            if is_tirocinio[i]:
                start = all_dates_dt[i].day
                end = start
                while i + 1 < len(all_dates_dt) and is_tirocinio[i + 1]:
                    i += 1
                    end = all_dates_dt[i].day
                if start == end:
                    ranges.append(f"{start}")
                else:
                    ranges.append(f"{start}-{end}")
            i += 1
        return ",".join(ranges) if ranges else "-"

    def _desiderata_entry_str(self, day, shifts):
        """
        Helper to format a desiderata entry for the richieste table.
        If compact_desiderata_in_richieste_table is True, returns e.g. 03P, 14PN.
        If False, returns e.g. 3 (NO POME), 14 (NO POME/NO NOTTE)
        """
        # Map shift to code and label
        shift_map = {
            "morning": ("M", "NO MATT"),
            "afternoon": ("P", "NO POME"), 
            "night": ("N", "NO NOTTE"),
            "mp": ("MP", "NO MP"),
            "split_mp": ("SMP", "NO SMP"),
            "weekend": ("W", "NO WEEKEND"),
        }
        if self.compact_desiderata_in_richieste_table:
            # Compact: 03P, 14PN
            codes = []
            for s in shifts:
                code = shift_map.get(s, (s.upper(), s.upper()))[0]
                codes.append(code)
            # Always use two digits for day
            return f"{int(day):02d}{''.join(codes)}"
        else:
            # Verbose: 3 (NO POME), 14 (NO POME/NO NOTTE)
            labels = []
            for s in shifts:
                label = shift_map.get(s, (s.upper(), s.upper()))[1]
                labels.append(label)
            return f"{int(day)} ({'/'.join(labels)})"

    def create_doc(self, settings=None, constraint_violations=None):
        # --- LOAD JSON AND PARSE SCHEDULE ---
        with open(self.json_path, encoding="utf-8") as f:
            data = json.load(f)

        schedule = data["schedule"]
        violations = constraint_violations or {}
        people_ids = sorted(schedule.keys())
        all_dates = set()
        for person_sched in schedule.values():
            all_dates.update(person_sched.keys())
        all_dates = sorted(all_dates)

        # Load violations if present and setting enabled
        show_violations = False
        violations_by_date = {}
        if settings and settings.get("docx_output", {}).get("show_violations"):
            show_violations = True
            for vlist in violations.values():
                for v in vlist:
                    # v is now a dict/object
                    vdate = v.get("date")
                    if vdate:
                        if vdate not in violations_by_date:
                            violations_by_date[vdate] = []
                        violations_by_date[vdate].append(v)

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
            # --- Find vacation pids for this date using the vacations section ---
            vacations = data.get("vacations", {})
            vacation_pids = []
            for pid in people_ids:
                if date_str in vacations.get(pid, []):
                    vacation_pids.append(pid)
            desiderata_cell = self.get_desiderata(date_str, desiderata, people_ids, vacation_pids)
            tirocinio_cell = self.get_internships(date_str, tirocinio, people_ids)
            # --- ASSENZE: Only MONTO/SMONTO NOTTE and people on vacation ---
            assenze_labels = []
            # Track which pids are MONTO/SMONTO for colorizing
            monto_pids = night_monto_map.get(date_str, [])
            smonto_pids = night_smonta_map.get(date_str, [])
            for pid in monto_pids:
                assenze_labels.append((pid, self.night_shift_labels['start']))
            for pid in smonto_pids:
                assenze_labels.append((pid, self.night_shift_labels['end']))
            
            # Add Saturday night rest (recupero) entries
            for pid in people_ids:
                shifts = schedule[pid].get(date_str, [])
                if 'rest_after_saturday_night' in shifts:
                    assenze_labels.append((pid, 'RECUPERO'))
            # Only add vacation pids if allowed by show_vacations_on_holidays or not a weekend/holiday
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            is_weekend = dt.weekday() in (5, 6)
            is_holiday = date_str in holidays
            for pid in vacation_pids:
                if (
                    self.show_vacations_on_holidays
                    or (not is_weekend and not is_holiday)
                ):
                    if (pid, self.night_shift_labels['start']) not in assenze_labels and (pid, self.night_shift_labels['end']) not in assenze_labels:
                        assenze_labels.append((pid, None))
            # --- Write ASSENZE with color for MONTO/SMONTO NOTTE ---
            cells = [giorno, mattino, pomeriggio, notte, desiderata_cell, tirocinio_cell, ""]
            tr = table.add_row().cells
            for i, val in enumerate(cells[:-1]):
                tr[i].text = val
                for paragraph in tr[i].paragraphs:
                    for run in paragraph.runs:
                        run.font.name = self.font_name
                tr[i].width = Inches(self.column_widths[i])
            # Compose ASSENZE cell with color for MONTO/SMONTO NOTTE and violations
            assenze_cell = tr[-1]
            p = assenze_cell.paragraphs[0]
            # Write MONTO/SMONTO NOTTE/vacation as before
            for idx2, (pid, label) in enumerate(assenze_labels):
                if idx2 > 0:
                    p.add_run(", ")
                if label:
                    run = p.add_run(f"{pid} ({label})")
                    # Use green color for all labels (MONTO/SMONTO NOTTE and RECUPERO)
                    run.font.color.rgb = RGBColor(
                        int(self.night_shift_color[0:2], 16),
                        int(self.night_shift_color[2:4], 16),
                        int(self.night_shift_color[4:6], 16)
                    )
                else:
                    p.add_run(str(pid))
            # Add violations for this date if enabled
            if show_violations and date_str in violations_by_date:
                if assenze_labels:
                    p.add_run("; ")
                for idxv, v in enumerate(violations_by_date[date_str]):
                    v_type = v.get("type", "")
                    # Only show if type is in show_violation_types and show_violations is True
                    if v_type in self.show_violation_types:
                        if idxv > 0:
                            p.add_run("\n")
                        constraint_id = v.get("constraint_id", str(v))
                        person_id = v.get("person_id", "")
                        constraint_name = v.get("name", "")
                        constraint_type = v.get("type", "")
                        if person_id:
                            run = p.add_run(f"[{constraint_type} {person_id}]")
                        else:
                            run = p.add_run(f"[{constraint_type}]")
                        run.font.color.rgb = RGBColor(0xC6, 0x1A, 0x09)

            assenze_cell.width = Inches(self.column_widths[-1])
            if is_weekend:
                self.set_row_bg_color(table.rows[-1], self.weekend_color)
            elif is_holiday:
                self.set_row_bg_color(table.rows[-1], self.holiday_color)

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

        # --- ADD SUMMARY TABLE FOR WEEKEND/NOTTE SHIFTS ---
        # Load statistics from JSON if available
        with open(self.json_path, encoding="utf-8") as f:
            data = json.load(f)
        staff_stats = data.get("staff_statistics", {})
        people_ids = sorted(staff_stats.keys())

        # Prepare summary data
        summary = []
        for pid in people_ids:
            stats = staff_stats[pid]
            # Saturday shifts
            sabato = []
            sabato += ["X" for _ in range(stats.get("saturday_m", 0))]
            sabato += ["X" for _ in range(stats.get("saturday_p", 0))]
            sabato += ["X̲" for _ in range(stats.get("saturday_mp", 0))]  # Underlined X for MP
            sabato += ["X̲" for _ in range(stats.get("night_saturday", 0))]  # Underlined X for night

            # Holidays (holidays + Sundays)
            festivo = []
            festivo += ["X" for _ in range(stats.get("holiday_m", 0))]
            festivo += ["X" for _ in range(stats.get("holiday_p", 0))]
            festivo += ["X̲" for _ in range(stats.get("holiday_mp", 0))]
            festivo += ["X̲" for _ in range(stats.get("night_holiday", 0))]
            festivo += ["X" for _ in range(stats.get("sunday_m", 0))]
            festivo += ["X" for _ in range(stats.get("sunday_p", 0))]
            festivo += ["X̲" for _ in range(stats.get("sunday_mp", 0))]
            festivo += ["X̲" for _ in range(stats.get("night_sunday", 0))]

            # Nights (all nights)
            notte = ["X̲" for _ in range(stats.get("night_shifts", 0))]

            # Totals in hours (MP and N = 12h, M or P = 6h)
            tot_we_notti_hours = (
                stats.get("saturday_m", 0) * 6 +
                stats.get("saturday_p", 0) * 6 +
                stats.get("saturday_mp", 0) * 12 +
                stats.get("night_saturday", 0) * 12 +
                stats.get("holiday_m", 0) * 6 +
                stats.get("holiday_p", 0) * 6 +
                stats.get("holiday_mp", 0) * 12 +
                stats.get("night_holiday", 0) * 12 +
                stats.get("sunday_m", 0) * 6 +
                stats.get("sunday_p", 0) * 6 +
                stats.get("sunday_mp", 0) * 12 +
                stats.get("night_sunday", 0) * 12 +
                stats.get("night_shifts", 0) * 12
            )

            summary.append({
                "person": pid,
                "sabato": " ".join(sabato) if sabato else "-",
                "festivo": " ".join(festivo) if festivo else "-",
                "notte": " ".join(notte) if notte else "-",
                "tot_we_notti": tot_we_notti_hours  # now in hours
            })

        # Add the summary table to the doc
        p = doc.add_paragraph("\n\n")
        table2 = doc.add_table(rows=1 + len(summary), cols=5)
        table2.style = "Table Grid"
        # Set custom (narrower) column widths for the summary table
        summary_col_widths = [1.0, 0.7, 0.7, 0.7, 0.9]  # in inches

        headers = ["PERSONA", "SABATO", "FESTIVO", "NOTTE", "TOT WE/NOTTI"]
        for i, h in enumerate(headers):
            cell = table2.cell(0, i)
            cell.text = h
            for run in cell.paragraphs[0].runs:
                run.bold = True
            # Set column width for header
            cell.width = Inches(summary_col_widths[i])
            table2.columns[i].width = Inches(summary_col_widths[i])

        for row_idx, row in enumerate(summary, 1):
            table2.cell(row_idx, 0).text = row["person"]
            table2.cell(row_idx, 1).text = row["sabato"]
            table2.cell(row_idx, 2).text = row["festivo"]
            table2.cell(row_idx, 3).text = row["notte"]
            table2.cell(row_idx, 4).text = str(row["tot_we_notti"])
            # Set column widths for each cell in the row
            for col_idx in range(5):
                table2.cell(row_idx, col_idx).width = Inches(summary_col_widths[col_idx])
                table2.columns[col_idx].width = Inches(summary_col_widths[col_idx])
            # Make row a little thicker by increasing minimum row height
            tr = table2.rows[row_idx]._tr
            trPr = tr.get_or_add_trPr()
            trHeight = OxmlElement('w:trHeight')
            trHeight.set(qn('w:val'), "400")  # 400 twips ≈ 0.28 cm, adjust as needed
            trHeight.set(qn('w:hRule'), "atLeast")
            trPr.append(trHeight)

        # Also set header row height
        tr = table2.rows[0]._tr
        trPr = tr.get_or_add_trPr()
        trHeight = OxmlElement('w:trHeight')
        trHeight.set(qn('w:val'), "400")
        trHeight.set(qn('w:hRule'), "atLeast")
        trPr.append(trHeight)

        # --- ADD RICHIESTE TABLE ---
        p = doc.add_paragraph("\n\n")
        run = p.add_run("RICHIESTE: ")
        run.bold = True
        run.underline = True

        # Prepare richieste data
        desiderata = data.get("desiderata", {})
        tirocinio = data.get("tirocinio", {})
        vacations = data.get("vacations", {})
        people_ids = sorted(schedule.keys())

        richieste_rows = []
        for pid in people_ids:
            # Tirocinio: compacted ranges including surrounded weekends/holidays
            tirocinio_days = tirocinio.get(pid, [])
            tirocinio_str = self.compact_tirocinio_ranges(
                tirocinio_days,
                all_dates,
                holidays
            )

            # Desiderata: list of (day, shift) as e.g. 12M, 15N, 18MP
            desiderata_entries = []
            weekend_days = set()
            ferie_dates = set(vacations.get(pid, []))
            for entry in desiderata.get(pid, []):
                # Skip if this desiderata is a vacation (all 3 shifts forbidden)
                if set(entry.get("shifts", [])) == {"morning", "afternoon", "night"}:
                    continue
                # Skip if this desiderata is a tirocinio (not present in desiderata, but for safety)
                # (No standard for tirocinio in desiderata, so nothing to skip here)
                day = entry["date"].split("-")[2]
                is_weekend_shift = any(s == "weekend" for s in entry["shifts"])
                # Only add to desiderata_entries if not a weekend shift
                if not is_weekend_shift:
                    desiderata_entries.append(self._desiderata_entry_str(day, entry["shifts"]))
                # Also collect weekends for desiderata weekend column
                dt = datetime.strptime(entry["date"], "%Y-%m-%d")
                if dt.weekday() in (5, 6) or is_weekend_shift:
                    weekend_days.add(day)
            desiderata_str = ", ".join(desiderata_entries) if desiderata_entries else "-"

            # Desiderata weekend: group consecutive days
            weekend_days_sorted = sorted(int(d) for d in weekend_days)
            weekend_ranges = []
            if weekend_days_sorted:
                start = prev = weekend_days_sorted[0]
                for d in weekend_days_sorted[1:]:
                    if d == prev + 1:
                        prev = d
                    else:
                        if start == prev:
                            weekend_ranges.append(f"{start}")
                        else:
                            weekend_ranges.append(f"{start}-{prev}")
                        start = prev = d
                if start == prev:
                    weekend_ranges.append(f"{start}")
                else:
                    weekend_ranges.append(f"{start}-{prev}")
            desiderata_weekend_str = ", ".join(weekend_ranges) if weekend_ranges else "-"

            # Ferie: number of days (only weekdays, not weekends/holidays)
            ferie_count = 0
            for ferie_date in vacations.get(pid, []):
                dt = datetime.strptime(ferie_date, "%Y-%m-%d")
                if dt.weekday() < 5 and ferie_date not in holidays:
                    ferie_count += 1

            richieste_rows.append([pid, tirocinio_str, desiderata_str, desiderata_weekend_str, str(ferie_count)])

        # Add richieste table
        table3 = doc.add_table(rows=1 + len(richieste_rows), cols=5)
        table3.style = "Table Grid"
        headers = ["NOME", "TIROCINIO", "DESIDERATA", "DESIDERATA WEEKEND", "FERIE"]
        for i, h in enumerate(headers):
            cell = table3.cell(0, i)
            cell.text = h
            for run in cell.paragraphs[0].runs:
                run.bold = True

        for row_idx, row in enumerate(richieste_rows, 1):
            for col_idx, val in enumerate(row):
                table3.cell(row_idx, col_idx).text = val

        doc.save(self.doc_path)
        print(f"{self.doc_path} created.")


if __name__ == "__main__":
    # Example usage with custom settings
    creator = ScheduleDocxCreator(
        json_path="output/schedule_output.json",
        doc_path="output/schedule_output.docx",
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
