-- Yesterday's emails from Exchange / "My Inbox" -> ~/Desktop/emails_yesterday

set outDir to POSIX path of ((path to desktop) as text) & "emails_yesterday"
do shell script "mkdir -p " & quoted form of outDir

-- compute strict yesterday [00:00 -> 23:59:59]
set n to (current date)
set m to n
set time of m to 0
set s to m - 1 * days
set e to m - 1

tell application "Mail"
	-- If your inbox is actually named "INBOX", change "My Inbox" to "INBOX" below.
	set mb to mailbox "My Inbox" of account "Exchange"
	set msgs to (every message of mb whose (date received ³ s) and (date received ² e))
	
	set k to 1
	repeat with m in msgs
		set raw to source of m
		set rdate to date received of m
		
		-- build timestamp YYYYMMDD_HHMMSS in pure AppleScript
		set yy to (year of rdate) as integer
		set mo to (month of rdate) as integer
		set dd to (day of rdate) as integer
		set hh to (hours of rdate) as integer
		set mm to (minutes of rdate) as integer
		set ss to (seconds of rdate) as integer
		set mo2 to rich text -2 thru -1 of ("0" & mo)
		set dd2 to rich text -2 thru -1 of ("0" & dd)
		set hh2 to rich text -2 thru -1 of ("0" & hh)
		set mm2 to rich text -2 thru -1 of ("0" & mm)
		set ss2 to rich text -2 thru -1 of ("0" & ss)
		set stamp to (yy as rich text) & mo2 & dd2 & "_" & hh2 & mm2 & ss2
		
		set fpath to outDir & "/" & stamp & "_" & k & ".eml"
		set f to open for access (POSIX file fpath as rich text) with write permission
		try
			set eof of f to 0
			write raw to f
		end try
		close access f
		set k to k + 1
	end repeat
end tell

return outDir
