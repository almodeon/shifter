import csv
from datetime import datetime, timedelta, date
from typing import List, Dict, Any, Optional, Tuple
import os

class DataLoader:
    def __init__(self, logger=None):
        """Initialize data loader with optional logger"""
        self.logger = logger
        self.supported_formats = ['csv', 'xls', 'xlsx']
        
        # Try to import pandas and openpyxl for Excel support
        self.pandas_available = False
        self.excel_available = False
        
        try:
            import pandas as pd
            self.pandas_available = True
            self.pd = pd
            
            # Check for Excel engine support
            try:
                import openpyxl
                self.excel_available = True
            except ImportError:
                try:
                    import xlrd
                    self.excel_available = True
                except ImportError:
                    pass
                    
        except ImportError:
            pass
    
    def _log(self, level: str, message: str):
        """Internal logging helper"""
        if self.logger:
            self.logger.log('data_loading', level, message)
        elif level == 'error':
            print(f"ERROR: {message}")
    
    def load_people_data(self, file_path: str, log_level: str = 'info') -> Dict[str, Any]:
        """Load person constraints from file (supports CSV, XLS, XLSX)"""
        if not os.path.exists(file_path):
            self._log('error', f"File not found: {file_path}")
            return self._create_test_data()
        
        file_ext = os.path.splitext(file_path)[1].lower()
        
        if file_ext == '.csv':
            return self._load_people_from_csv(file_path, log_level)
        elif file_ext in ['.xls', '.xlsx']:
            if not self.pandas_available or not self.excel_available:
                self._log('error', f"Excel support not available. Install pandas and openpyxl/xlrd to read {file_ext} files")
                return self._create_test_data()
            return self._load_people_from_excel(file_path, log_level)
        else:
            self._log('error', f"Unsupported file format: {file_ext}. Supported formats: {self.supported_formats}")
            return self._create_test_data()
    
    def load_night_dates(self, file_path: str, log_level: str = 'info') -> List[datetime.date]:
        """Load required night dates from file (supports CSV, XLS, XLSX)"""
        if not os.path.exists(file_path):
            self._log('error', f"File not found: {file_path}")
            return []
        
        file_ext = os.path.splitext(file_path)[1].lower()
        
        if file_ext == '.csv':
            return self._load_nights_from_csv(file_path, log_level)
        elif file_ext in ['.xls', '.xlsx']:
            if not self.pandas_available or not self.excel_available:
                self._log('error', f"Excel support not available. Install pandas and openpyxl/xlrd to read {file_ext} files")
                return []
            return self._load_nights_from_excel(file_path, log_level)
        else:
            self._log('error', f"Unsupported file format: {file_ext}. Supported formats: {self.supported_formats}")
            return []
    
    def _load_people_from_csv(self, csv_file: str, log_level: str) -> Dict[str, Any]:
        """Load person data from CSV file"""
        people_data = {}
        
        # Try different encodings
        encodings = ['utf-8', 'utf-8-sig', 'latin1', 'cp1252']
        
        for encoding in encodings:
            try:
                with open(csv_file, 'r', encoding=encoding) as file:
                    reader = csv.DictReader(file)
                    
                    if log_level in ['info', 'debug']:
                        self._log('info', f"Columns found in {csv_file}: {reader.fieldnames}")
                    
                    for row in reader:
                        person_data = self._parse_person_row(row, log_level)
                        if person_data:
                            people_data[person_data['id']] = person_data['data']
                
                break  # Successfully read with this encoding
                
            except (UnicodeDecodeError, KeyError) as e:
                if encoding == encodings[-1]:  # Last encoding tried
                    self._log('error', f"Could not read {csv_file} with any encoding: {e}")
                    return self._create_test_data()
                continue
        
        return people_data
    
    def _load_people_from_excel(self, excel_file: str, log_level: str) -> Dict[str, Any]:
        """Load person data from Excel file"""
        try:
            # Try to read Excel file
            df = self.pd.read_excel(excel_file, engine='openpyxl' if excel_file.endswith('.xlsx') else None)
            
            if log_level in ['info', 'debug']:
                self._log('info', f"Columns found in {excel_file}: {list(df.columns)}")
            
            people_data = {}
            
            for _, row in df.iterrows():
                # Convert pandas Series to dict
                row_dict = row.to_dict()
                person_data = self._parse_person_row(row_dict, log_level)
                if person_data:
                    people_data[person_data['id']] = person_data['data']
            
            return people_data
            
        except Exception as e:
            self._log('error', f"Error reading Excel file {excel_file}: {e}")
            return self._create_test_data()
    
    def _parse_person_row(self, row: Dict, log_level: str) -> Optional[Dict]:
        """Parse a single person row from CSV or Excel"""
        try:
            # Handle potential BOM or encoding issues in column names
            person_key = None
            for key in row.keys():
                if key and ('persona' in str(key).lower() or str(key).strip() == 'Persona'):
                    person_key = key
                    break
            
            if not person_key:
                if log_level in ['error', 'info', 'debug']:
                    self._log('error', f"Available keys: {list(row.keys())}")
                raise KeyError("Could not find 'Persona' column")
            
            person_id = str(row[person_key]).strip()
            if not person_id or person_id.lower() in ['nan', 'none', '']:
                return None
            
            # Parse night shift availability
            night_available = True  # Default to available
            notti_col = 'Notti'
            if notti_col in row and str(row[notti_col]).strip().upper() == 'N':
                night_available = False
            
            # Parse forbidden shifts
            forbidden_shifts = []
            for i in range(1, 7):
                shift_col = f'Turno vietato {i}'
                if shift_col in row and row[shift_col] and str(row[shift_col]).strip():
                    parsed_shift = self._parse_shift(str(row[shift_col]))
                    if parsed_shift:
                        forbidden_shifts.append(parsed_shift)
            
            # Parse vacation dates (Ferie) and convert to forbidden shifts
            ferie_col = 'Ferie'
            if ferie_col in row and row[ferie_col] and str(row[ferie_col]).strip():
                vacation_shifts = self._parse_vacation_dates(str(row[ferie_col]), log_level)
                forbidden_shifts.extend(vacation_shifts)
                if log_level in ['info', 'debug']:
                    self._log('info', f"Person {person_id}: Added {len(vacation_shifts)} vacation-based forbidden shifts")
            
            # Parse forbidden weekends
            forbidden_weekends = []
            for i in range(1, 4):
                weekend_col = f'Weekend vietato {i}'
                if weekend_col in row and row[weekend_col] and str(row[weekend_col]).strip():
                    parsed_date = self._parse_date(str(row[weekend_col]))
                    if parsed_date:
                        forbidden_weekends.append(parsed_date)
            
            person_data = {
                'forbidden_shifts': forbidden_shifts,
                'forbidden_weekends': forbidden_weekends,
                'night_available': night_available
            }
            
            if log_level in ['info', 'debug']:
                self._log('info', f"Person {person_id}: Night shifts available = {night_available}")
            
            return {'id': person_id, 'data': person_data}
            
        except Exception as e:
            self._log('error', f"Error parsing person row: {e}")
            return None
    
    def _load_nights_from_csv(self, csv_file: str, log_level: str) -> List[datetime.date]:
        """Load night dates from CSV file"""
        night_dates = []
        
        # Try different encodings
        encodings = ['utf-8', 'utf-8-sig', 'latin1', 'cp1252']
        
        for encoding in encodings:
            try:
                with open(csv_file, 'r', encoding=encoding) as file:
                    content = file.read()
                    lines = content.strip().split('\n')
                    
                    if log_level in ['info', 'debug']:
                        self._log('info', f"Reading required night dates from {csv_file}...")
                    
                    for line in lines:
                        date_str = line.strip()
                        # Skip header line or empty lines
                        if date_str and not ('notte' in date_str.lower() or 'richiesta' in date_str.lower()):
                            parsed_date = self._parse_date(date_str)
                            if parsed_date:
                                night_dates.append(parsed_date)
                                if log_level in ['debug']:
                                    self._log('debug', f"  Required night date: {parsed_date}")
                
                break  # Successfully read with this encoding
                
            except (UnicodeDecodeError, FileNotFoundError) as e:
                if encoding == encodings[-1]:  # Last encoding tried
                    self._log('error', f"Could not read {csv_file}: {e}")
                continue
        
        return night_dates
    
    def _load_nights_from_excel(self, excel_file: str, log_level: str) -> List[datetime.date]:
        """Load night dates from Excel file"""
        try:
            df = self.pd.read_excel(excel_file, engine='openpyxl' if excel_file.endswith('.xlsx') else None, header=None)
            
            if log_level in ['info', 'debug']:
                self._log('info', f"Reading required night dates from {excel_file}...")
            
            night_dates = []
            
            for _, row in df.iterrows():
                for cell_value in row:
                    if cell_value and not self.pd.isna(cell_value):
                        cell_str = str(cell_value).strip()
                        # Skip header-like content
                        if cell_str and not ('notte' in cell_str.lower() or 'richiesta' in cell_str.lower()):
                            # Handle Excel date objects
                            if isinstance(cell_value, datetime):
                                night_dates.append(cell_value.date())
                                if log_level in ['debug']:
                                    self._log('debug', f"  Required night date: {cell_value.date()}")
                            else:
                                parsed_date = self._parse_date(cell_str)
                                if parsed_date:
                                    night_dates.append(parsed_date)
                                    if log_level in ['debug']:
                                        self._log('debug', f"  Required night date: {parsed_date}")
            
            return night_dates
            
        except Exception as e:
            self._log('error', f"Error reading Excel file {excel_file}: {e}")
            return []
    
    def _parse_shift(self, shift_str: str) -> Optional[Dict]:
        """Parse shift string like '03/10/2025 PN' into date and shift types"""
        try:
            parts = shift_str.strip().split()
            if len(parts) != 2:
                return None
            
            date_str, shift_types = parts
            date = self._parse_date(date_str)
            if not date:
                return None
            
            shifts = []
            for char in shift_types:
                if char == 'M':
                    shifts.append('morning')
                elif char == 'P':
                    shifts.append('afternoon')
                elif char == 'N':
                    shifts.append('night')
            
            return {'date': date, 'shifts': shifts}
        except:
            return None
    
    def _parse_date(self, date_str: str) -> Optional[datetime.date]:
        """Parse date string in DD/MM/YYYY format"""
        try:
            return datetime.strptime(date_str.strip(), '%d/%m/%Y').date()
        except:
            return None
    
    def _parse_vacation_dates(self, vacation_str: str, log_level: str = 'info') -> List[Dict]:
        """Parse vacation dates string and convert to forbidden shifts"""
        forbidden_shifts = []
        
        try:
            # Split by comma and parse each date
            date_strings = [d.strip() for d in vacation_str.split(',') if d.strip()]
            
            for date_str in date_strings:
                vacation_date = self._parse_date(date_str)
                if vacation_date:
                    # 1. Forbid all shifts (MPN) on the vacation day itself
                    forbidden_shifts.append({
                        'date': vacation_date,
                        'shifts': ['morning', 'afternoon', 'night']
                    })
                    
                    # 2. Forbid night shift on the day BEFORE vacation
                    day_before = vacation_date - timedelta(days=1)
                    forbidden_shifts.append({
                        'date': day_before,
                        'shifts': ['night']
                    })
                    
                    if log_level in ['debug']:
                        self._log('debug', f"  Vacation {vacation_date}: blocked MPN on {vacation_date}, blocked N on {day_before}")
        except Exception as e:
            self._log('error', f"Error parsing vacation dates '{vacation_str}': {e}")
        
        return forbidden_shifts
    
    def _create_test_data(self) -> Dict[str, Any]:
        """Create minimal test data when file loading fails"""
        self._log('info', "Creating minimal test data for demonstration")
        people_data = {}
        for i in range(1, 6):
            people_data[str(i)] = {
                'forbidden_shifts': [],
                'forbidden_weekends': [],
                'night_available': True
            }
        return people_data
    
    def validate_data(self, people_data: Dict, night_dates: List) -> Tuple[bool, List[str]]:
        """Validate loaded data and return (is_valid, errors)"""
        errors = []
        
        # Validate people data
        if not people_data:
            errors.append("No people data loaded")
        else:
            for person_id, person_data in people_data.items():
                if not isinstance(person_data, dict):
                    errors.append(f"Invalid data structure for person {person_id}")
                    continue
                
                required_keys = ['forbidden_shifts', 'forbidden_weekends', 'night_available']
                for key in required_keys:
                    if key not in person_data:
                        errors.append(f"Missing '{key}' for person {person_id}")
        
        # Validate night dates
        if not isinstance(night_dates, list):
            errors.append("Night dates must be a list")
        else:
            for i, date_obj in enumerate(night_dates):
                if not isinstance(date_obj, date):
                    errors.append(f"Invalid date format at position {i}: {date_obj}")
        
        return len(errors) == 0, errors
    
    def get_supported_formats(self) -> List[str]:
        """Get list of supported file formats"""
        formats = ['csv']
        if self.pandas_available and self.excel_available:
            formats.extend(['xls', 'xlsx'])
        return formats
    
    def check_dependencies(self) -> Dict[str, bool]:
        """Check availability of optional dependencies"""
        return {
            'pandas': self.pandas_available,
            'excel_support': self.excel_available,
            'csv_support': True  # Always available
        }
