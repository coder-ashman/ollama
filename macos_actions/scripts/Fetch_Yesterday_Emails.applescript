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
	
	set fragments to {}
	
	tell application "Mail"
		set targetMailbox to mailbox "My Inbox" of account "Exchange"
		set messageList to (every message of targetMailbox whose (date received is greater than or equal to startWindow) and (date received is less than or equal to endWindow))
		repeat with eachMessage in messageList
			set end of fragments to my message_fragment(eachMessage, targetMailbox)
		end repeat
	end tell
	
	set AppleScript's text item delimiters to ","
	set joined to ""
	if fragments is not {} then set joined to fragments as text
	set AppleScript's text item delimiters to ""
	
	return "{\"messages\":[" & joined & "]}"
end collect_yesterday_messages

on message_fragment(msg, mb)
	using terms from application "Mail"
		set subjectText to my safe_text(subject of msg)
		set senderText to my safe_text(sender of msg)
		set idText to my safe_text(message id of msg)
		set readFlag to read status of msg
		set dateText to my safe_text(date received of msg as string)
		set mailboxText to my safe_text(name of mb as text)
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
end message_fragment

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
	set trimmed to my trim_whitespace(bodyText)
	if (length of trimmed) > 200 then set trimmed to text 1 thru 200 of trimmed
	return my escape_json(trimmed)
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
	set charList to characters of t
	repeat while (charList is not {}) and my is_whitespace(item 1 of charList)
		if (count of charList) = 1 then
			set charList to {}
		else
			set charList to rest of charList
		end if
		if charList is {} then return ""
	end repeat
	repeat while (charList is not {}) and my is_whitespace(item -1 of charList)
		if (count of charList) = 1 then
			set charList to {}
		else
			set charList to items 1 thru -2 of charList
		end if
		if charList is {} then return ""
	end repeat
	return charList as text
end trim_whitespace

on is_whitespace(ch)
	if ch is space then return true
	if ch is tab then return true
	if ch is return then return true
	if ch is linefeed then return true
	return false
end is_whitespace
