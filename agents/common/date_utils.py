from datetime import datetime, timedelta
import re

class DateUtils:
    """Natural Language Date Parser for Korean"""
    
    WEEKDAYS = {
        "월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6,
        "월요일": 0, "화요일": 1, "수요일": 2, "목요일": 3, "금요일": 4, "토요일": 5, "일요일": 6
    }
    
    @staticmethod
    def parse_relative_date(text: str, base_date: datetime = None) -> str:
        """
        Parses relative date strings (e.g., "이번주 금요일", "내일") into 'YYYY-MM-DD'.
        Returns None if parsing fails.
        """
        if base_date is None:
            # Default to KST (UTC+9)
            base_date = datetime.now() + timedelta(hours=9)
            
        text = text.lower().replace(" ", "") # Remove spaces and lowercase
        
        # 1. Simple Keywords (Check longest/specific first)
        # "day after tomorrow" matches "tomorrow", so check it first.
        if any(x in text for x in ["모레", "내일모레", "thedayaftertomorrow", "dayaftertomorrow"]):
            return (base_date + timedelta(days=2)).strftime("%Y-%m-%d")
            
        if any(x in text for x in ["내일", "명일", "tomorrow"]):
            return (base_date + timedelta(days=1)).strftime("%Y-%m-%d")
            
        if any(x in text for x in ["오늘", "금일", "today"]):
            return base_date.strftime("%Y-%m-%d")
            
        # 2. Weekday Logic (이번주/다음주/다다음주 + 요일/욜)
        # Korean Regex: Matches (Modifier)? (WeekdayChar) (Suffix)?
        # e.g. "이번주 금요일", "이번주 금욜", "금요", "금"
        week_match_kr = re.search(r"(이번주|다음주|다다음주)?([월화수목금토일])(?:요일|요|욜)?", text)
        
        # English Regex (this/next + weekday)
        week_match_en = re.search(r"(this|next)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", text)

        if week_match_kr:
            modifier = week_match_kr.group(1) or "이번주"
            day_char = week_match_kr.group(2) # "월", "화", ...
            # Map single char to int
            # WEEKDAYS has "월", "월요일" etc. checking char is enough.
            target_weekday = DateUtils.WEEKDAYS.get(day_char)
            
            days_ahead = target_weekday - base_date.weekday()
            
            if modifier == "다음주":
                days_ahead += 7
            elif modifier == "다다음주":
                days_ahead += 14
                
            # If "this friday" is requested on Friday, usually means TODAY.
            # If "this friday" is requested on Saturday, it's ambiguous (past or next?).
            # For "This Week", we stick to the current iso week boundaries or simple forward look?
            # Simple logic: "This X" usually means the X inside (Today..Today+6) range? 
            # Or strictly "The X in the current week scope"?
            # Let's use simple logic: If result is in past, add 7 days? 
            # No, "This Friday" on Saturday usually refers to the PAST Friday.
            # But users scheduling meetings usually mean FUTURE.
            # Let's keep strict "current relative week" logic for now.
             
            return (base_date + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

        elif week_match_en:
            modifier = week_match_en.group(1) or "this"
            day_str = week_match_en.group(2)
            
            eng_weekdays = {
                "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6
            }
            target_weekday = eng_weekdays.get(day_str)
            
            days_ahead = target_weekday - base_date.weekday()
            
            if modifier == "next":
                days_ahead += 7
                
            return (base_date + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
            
        return None

    @staticmethod
    def parse_datetime_expression(text: str, base_datetime: datetime = None) -> str:
        """
        Parses natural language datetime expressions into ISO 8601 format.
        Handles Korean and English expressions for both date and time.
        
        Examples:
            "내일 오후 3시 30분" -> "2026-02-12T15:30:00"
            "다음주 금요일 오전 10시" -> "2026-02-14T10:00:00"
            "오늘 오후 2시" -> "2026-02-11T14:00:00"
            "3시 30분" -> "2026-02-11T15:30:00" (assumes afternoon for 1-5pm)
        
        Returns None if parsing fails.
        """
        if base_datetime is None:
            # Default to KST (UTC+9)
            base_datetime = datetime.now() + timedelta(hours=9)
        
        # Parse date component
        date_str = DateUtils.parse_relative_date(text, base_datetime)
        if date_str is None:
            # No relative date found, use today
            date_str = base_datetime.strftime("%Y-%m-%d")
        
        # Parse time component
        time_str = DateUtils._parse_time(text)
        if time_str is None:
            # Default to 14:00 (2pm) if no time specified
            time_str = "14:00:00"
        
        return f"{date_str}T{time_str}"
    
    @staticmethod
    def _parse_time(text: str) -> str:
        """
        Parses time from Korean/English text.
        Returns "HH:MM:SS" format or None if parsing fails.
        
        Examples:
            "오후 3시 30분" -> "15:30:00"
            "오전 10시" -> "10:00:00"
            "3시 30분" -> "15:30:00" (assumes afternoon for 1-5)
            "15시" -> "15:00:00"
        """
        text = text.lower().replace(" ", "")
        
        # Pattern 1: 24-hour format (15시, 15:30)
        match_24h = re.search(r"(\d{1,2})[:시](\d{1,2})?", text)
        if match_24h and "오전" not in text and "오후" not in text:
            hour = int(match_24h.group(1))
            minute = int(match_24h.group(2)) if match_24h.group(2) else 0
            if hour >= 13:  # Already in 24h format
                return f"{hour:02d}:{minute:02d}:00"
        
        # Pattern 2: AM/PM format (오전/오후 + hour + optional minute)
        # Regex: (오전|오후)? + number + (시|:) + optional(number + 분)
        match_ampm = re.search(r"(오전|오후|am|pm)?(\d{1,2})[:시](\d{1,2})?[분]?", text)
        
        if match_ampm:
            period = match_ampm.group(1)  # None, "오전", "오후", "am", "pm"
            hour = int(match_ampm.group(2))
            minute = int(match_ampm.group(3)) if match_ampm.group(3) else 0
            
            # Determine if AM or PM
            if period in ["오후", "pm"]:
                if hour < 12:
                    hour += 12
            elif period in ["오전", "am"]:
                if hour == 12:
                    hour = 0
            else:
                # No AM/PM specified - use context-aware logic
                if 1 <= hour <= 5:
                    # 1-5시: Assume afternoon (회의는 대부분 오후)
                    hour += 12
                elif hour == 12:
                    # 12시: Noon
                    pass
                # 6-11시: Keep as is (morning hours)
            
            return f"{hour:02d}:{minute:02d}:00"
        
        return None
