use AppleScript version "2.8"
use scripting additions

on run
	return my collect_yesterday_messages()
end run

on collect_yesterday_messages()
	set startOfToday to current date
	set time of startOfToday to 0
	set startWindow to startOfToday - 1 * days
	set endWindow to startOfToday - 1
	
	set messageFragments to {}
	
	tell application "Mail"
		set targetMailbox to mailbox "My Inbox" of account "Exchange"
		set messageList to every message of targetMailbox whose (date received ≥ startWindow) and (date received ≤ endWindow)
		repeat with eachMessage in messageList
			set end of messageFragments to my json_fragment_for(eachMessage, name of targetMailbox)
		end repeat
	end tell
	
	set AppleScript's text item delimiters to ","
	if messageFragments is {}
		set joined to ""
	else
		set joined to messageFragments as text
	end if
	set AppleScript's text item delimiters to ""
	
	return "{\"messages\":[" & joined & "]}"
end collect_yesterday_messages

on json_fragment_for(msg, mailboxName)
	using terms from application "Mail"
		set subjectText to my safe_text(subject of msg)
		set senderText to my safe_text(sender of msg)
		set idText to my safe_text(message id of msg)
		set readFlag to (read status of msg)
		set dateText to my iso8601(date received of msg)
		set mailboxText to my safe_text(mailboxName as text)
		set snippetText to my snippet_from_content(msg)
	end using terms from
	
	set fragment to "{"
	set fragment to fragment & "\"subject\":\"" & subjectText & "\""
	set fragment to fragment & ",\"date_received\":\"" & dateText & "\""
	set fragment to fragment & ",\"sender\":\"" & senderText & "\""
	set fragment to fragment & ",\"message_id\":\"" & idText & "\""
	set fragment to fragment & ",\"read\":" & (my bool_text(readFlag))
	set fragment to fragment & ",\"mailbox\":\"" & mailboxText & "\""
	if snippetText is not "" then
		set fragment to fragment & ",\"snippet\":\"" & snippetText & "\""
	end if
	set fragment to fragment & "}"
	return fragment
end json_fragment_for

on snippet_from_content(msg)
	using terms from application "Mail"
		set bodyText to ""
		try
			set bodyText to content of msg as text
		on error
			set bodyText to ""
		end try
	end using terms from
	if bodyText is "" then return ""
	set trimmed to my escape_json(my trim_whitespace(bodyText))
	if (length of trimmed) > 200 then set trimmed to text 1 thru 200 of trimmed
	return trimmed
end snippet_from_content

on safe_text(candidate)
	if candidate is missing value then return ""
	return my escape_json(candidate as text)
end safe_text

on bool_text(flag)
	if flag is true then return "true"
	return "false"
end bool_text

on escape_json(t)
	set textOut to t
	set textOut to my replace_text("\\", "\\\\", textOut)
	set textOut to my replace_text("\"", "\\\"", textOut)
	set textOut to my replace_text(return, "\\n", textOut)
	set textOut to my replace_text(linefeed, "\\n", textOut)
	return textOut
end escape_json

on replace_text(findText, replaceText, sourceText)
	set AppleScript's text item delimiters to findText
	set parts to text items of sourceText
	set AppleScript's text item delimiters to replaceText
	set resultText to parts as text
	set AppleScript's text item delimiters to ""
	return resultText
end replace_text

on trim_whitespace(t)
	set theChars to characters of t
	repeat while theChars is not {} and my is_whitespace(item 1 of theChars)
		set theChars to rest of theChars
	repeat while theChars is not {} and my is_whitespace(item -1 of theChars)
		set theChars to items 1 thru -2 of theChars
	return theChars as text
end trim_whitespace

on is_whitespace(ch)
	if ch is space then return true
	if ch is tab then return true
	if ch is return then return true
	if ch is linefeed then return true
	return false
end is_whitespace

on iso8601(d)
	set yyyy to year of d as integer
	set mm to month of d as integer
	set dd to day of d as integer
	set hh to hours of d as integer
	set mi to minutes of d as integer
	set ss to seconds of d as integer
	set offsetSeconds to (time to GMT) of d * -1
	set sign to "+"
	if offsetSeconds < 0 then
		set sign to "-"
		set offsetSeconds to offsetSeconds * -1
	end if
	set offsetHours to offsetSeconds div hours
	set offsetMinutes to (offsetSeconds mod hours) div minutes
	return (yyyy as string) & "-" & my pad2(mm) & "-" & my pad2(dd) & "T" & my pad2(hh) & ":" & my pad2(mi) & ":" & my pad2(ss) & sign & my pad2(offsetHours) & ":" & my pad2(offsetMinutes)
end iso8601

on pad2(n)
	set nInt to n as integer
	if nInt < 10 then return "0" & nInt
	return nInt as string
end pad2
