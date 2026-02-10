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
            
        # 2. Weekday Logic (이번주/다음주/다다음주 + 요일)
        # Korean Regex
        week_match_kr = re.search(r"(이번주|다음주|다다음주)?([월화수목금토일]요일?)", text)
        
        # English Regex (this/next + weekday)
        week_match_en = re.search(r"(this|next)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", text)

        if week_match_kr:
            modifier = week_match_kr.group(1) or "이번주"
            day_str = week_match_kr.group(2)
            target_weekday = DateUtils.WEEKDAYS.get(day_str)
            
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
