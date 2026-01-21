import os
import subprocess
from datetime import datetime

def get_daily_git_logs():
    """Fetches git log for today."""
    try:
        # Get start of today (local time)
        since = datetime.now().strftime("%Y-%m-%d 00:00:00")
        
        # Git command to get commits since today start
        # Format: - [timestamp] commit_message (author)
        cmd = [
            "git", "log", 
            f"--since={since}", 
            "--pretty=format:- [%ai] %s (%an)",
            "--reverse"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error fetching git logs: {e}")
        return ""

def get_git_status():
    """Fetches staged and unstaged changes."""
    try:
        # Check staged changes
        staged = subprocess.run(["git", "diff", "--cached", "--name-only"], capture_output=True, text=True, check=True).stdout.strip()
        # Check unstaged changes
        unstaged = subprocess.run(["git", "diff", "--name-only"], capture_output=True, text=True, check=True).stdout.strip()
        
        status_msg = ""
        if staged:
            status_msg += "### Staged Changes (git add):\n"
            for f in staged.split("\n"):
                status_msg += f"- [STAGED] {f}\n"
            status_msg += "\n"
            
        if unstaged:
            status_msg += "### Unstaged Changes:\n"
            for f in unstaged.split("\n"):
                status_msg += f"- [MODIFIED] {f}\n"
            status_msg += "\n"
            
        return status_msg
    except subprocess.CalledProcessError:
        return ""

def save_report(commits, status):
    """Saves the content to outputs/daily-git-report/YYYY-MM-DD.md."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../outputs/daily-git-report"))
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
        
    file_path = os.path.join(output_dir, f"{today_str}.md")
    
    report_content = f"# Git Activity Report - {today_str}\n\n"
    
    if status:
        report_content += "## Current Workspace Status\n" + status
    
    report_content += "## Commits Today\n"
    if not commits:
        report_content += "No git commits found for today.\n"
    else:
        report_content += commits + "\n"
        
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(report_content)
    
    return file_path

if __name__ == "__main__":
    print("Generating daily git report...")
    commits = get_daily_git_logs()
    status = get_git_status()
    saved_path = save_report(commits, status)
    print(f"Report saved to: {saved_path}")
