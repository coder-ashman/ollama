-- Latest Friday -> Sunday emails from Exchange / "My Inbox" to ~/Desktop/emails_fri_to_sun

set outDir to POSIX path of ((path to desktop) as text) & "emails_fri_to_sun"
do shell script "mkdir -p " & quoted form of outDir

-- compute most recent Friday [00:00] to Sunday [23:59:59]
set n to (current date)
set m to n
set time of m to 0
set d to m
repeat while (weekday of d is not Friday)
	set d to d - 1 * days
end repeat
set s to d
set e to d + 3 * days - 1

tell application "Mail"
	activate
	-- if your inbox is really named "INBOX", change the next line to mailbox "INBOX" of account "Exchange"
	set mb to mailbox "My Inbox" of account "Exchange"
	set msgs to (every message of mb whose (date received ³ s) and (date received ² e))
	
	set k to 1
	repeat with m in msgs
		set raw to source of m
		set rdate to date received of m
		
		-- build timestamp YYYYMMDD_HHMMSS in pure AppleScript
		set y to (year of rdate) as integer
		set mo to (month of rdate) as integer
		set dy to (day of rdate) as integer
		set hh to (hours of rdate) as integer
		set mm to (minutes of rdate) as integer
		set ss to (seconds of rdate) as integer
		
		set mo2 to rich text -2 thru -1 of ("0" & mo)
		set dy2 to rich text -2 thru -1 of ("0" & dy)
		set hh2 to rich text -2 thru -1 of ("0" & hh)
		set mm2 to rich text -2 thru -1 of ("0" & mm)
		set ss2 to rich text -2 thru -1 of ("0" & ss)
		
		set stamp to (y as rich text) & mo2 & dy2 & "_" & hh2 & mm2 & ss2
		
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
