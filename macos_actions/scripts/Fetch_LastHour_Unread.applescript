use AppleScript version "2.8"
use scripting additions

property DEFAULT_LOOKBACK_HOURS : missing value
property LAST_LOOKBACK_HOURS : missing value

on run argv
	return my collect_unread_last_hour(argv)
end run

on collect_unread_last_hour(argv)
	set nowDate to current date
	set startWindow to my resolve_start_window(nowDate, argv)
	
	set folderNames to {}
	set messageBatches to {}
	
	tell application "Mail"
		set exchangeAccount to account "Exchange"
		set parentMailbox to mailbox "My Inbox" of exchangeAccount
		repeat with folderLabel in {"Rajesh Jayaraj", "Cassie Pizzurro"}
			try
				set childMailbox to mailbox folderLabel of parentMailbox
				set msgList to (every message of childMailbox whose (read status is false) and (date received is greater than or equal to startWindow) and (date received is less than or equal to nowDate))
				if msgList is not {} then
					set end of folderNames to (name of childMailbox as text)
					set end of messageBatches to msgList
				end if
			on error
				-- subfolder missing; skip
			end try
		end repeat
		set msgList to (every message of parentMailbox whose (read status is false) and (date received is greater than or equal to startWindow) and (date received is less than or equal to nowDate))
		if msgList is not {} then
			set end of folderNames to (name of parentMailbox as text)
			set end of messageBatches to msgList
		end if
	end tell
	
	set fragments to {}
	repeat with idx from 1 to count of messageBatches
		set mailboxMessages to item idx of messageBatches
		set mailboxName to item idx of folderNames
		set orderedMessages to my sort_messages(mailboxMessages)
		repeat with eachMessage in orderedMessages
			set end of fragments to my message_fragment(eachMessage, mailboxName)
		end repeat
	end repeat
	
	set AppleScript's text item delimiters to ","
	set joined to ""
	if fragments is not {} then set joined to fragments as text
	set AppleScript's text item delimiters to ""
	
	set windowStartText to my json_string(my format_local_timestamp(startWindow))
	set windowEndText to my json_string(my format_local_timestamp(nowDate))
	
	set windowEntries to {"\"start\":" & windowStartText, "\"end\":" & windowEndText}
	if my LAST_LOOKBACK_HOURS is not missing value then
		set end of windowEntries to "\"hours_back\":" & (LAST_LOOKBACK_HOURS as string)
	end if
	set windowJSON to "{" & my join_entries(windowEntries) & "}"
	
	set messagesJSON to "[" & joined & "]"
	return "{\"window\":" & windowJSON & ",\"messages\":" & messagesJSON & "}"
end collect_unread_last_hour

on resolve_start_window(nowDate, argv)
	set my LAST_LOOKBACK_HOURS to DEFAULT_LOOKBACK_HOURS
	set midnightAnchor to my start_of_day(nowDate)
	set hoursBack to my parse_hours_argument(argv)
	if hoursBack is missing value then return midnightAnchor
	
	try
		set my LAST_LOOKBACK_HOURS to hoursBack
		return nowDate - (hoursBack * hours)
	on error
		set my LAST_LOOKBACK_HOURS to DEFAULT_LOOKBACK_HOURS
		return midnightAnchor
	end try
end resolve_start_window

on start_of_day(nowDate)
	copy nowDate to startRef
	set time of startRef to 0
	return startRef
end start_of_day

on parse_hours_argument(argv)
	if argv is missing value then return DEFAULT_LOOKBACK_HOURS
	if (class of argv is not list) then return DEFAULT_LOOKBACK_HOURS
	
	set tokens to {}
	repeat with argItem in argv
		set argText to my trim_whitespace(argItem)
		if argText is not "" then set end of tokens to argText
	end repeat
	if tokens is {} then return DEFAULT_LOOKBACK_HOURS
	
	set hoursText to missing value
	
	set idx to 1
	repeat while idx ≤ count of tokens
		set token to item idx of tokens
		if token starts with "--hours=" then
			if (count characters of token) > 8 then
				set hoursText to text 9 thru -1 of token
			else
				set hoursText to ""
			end if
			exit repeat
		else if token = "--hours" then
			if idx < count of tokens then
				set hoursText to item (idx + 1) of tokens
			end if
			exit repeat
		else if token = "--lookback" then
			if idx < count of tokens then
				set hoursText to item (idx + 1) of tokens
			end if
			exit repeat
		else if token starts with "--lookback=" then
			if (count characters of token) > 11 then
				set hoursText to text 12 thru -1 of token
			else
				set hoursText to ""
			end if
			exit repeat
		end if
		set idx to idx + 1
	end repeat
	
	if hoursText is missing value then
		set candidate to item 1 of tokens
		if candidate does not start with "--" then
			set hoursText to candidate
		end if
	end if
	
	if hoursText is missing value then return DEFAULT_LOOKBACK_HOURS
	set cleaned to my trim_whitespace(hoursText)
	if cleaned is "" then return DEFAULT_LOOKBACK_HOURS
	set charCount to count characters of cleaned
	if charCount < 1 or charCount > 2 then return DEFAULT_LOOKBACK_HOURS
	
	try
		set hoursBack to cleaned as integer
	on error
		return DEFAULT_LOOKBACK_HOURS
	end try
	
	if hoursBack ≤ 0 then return DEFAULT_LOOKBACK_HOURS
	return hoursBack
end parse_hours_argument

on format_local_timestamp(dt)
	set datePart to date string of dt
	set timePart to time string of dt
	return datePart & " " & timePart
end format_local_timestamp

on join_entries(entries)
	if entries is missing value then return ""
	if entries is {} then return ""
	set AppleScript's text item delimiters to ","
	set combined to entries as text
	set AppleScript's text item delimiters to ""
	return combined
end join_entries

on json_string(candidate)
	return "\"" & my safe_text(candidate) & "\""
end json_string

on trim_whitespace(candidate)
	if candidate is missing value then return ""
	set textValue to candidate as text
	if textValue is "" then return ""
	
	set whitespaceChars to {" ", tab, return, linefeed}
	set startIndex to 1
	set endIndex to count of textValue
	
	repeat while startIndex ≤ endIndex
		set currentChar to character startIndex of textValue
		if currentChar is in whitespaceChars then
			set startIndex to startIndex + 1
		else
			exit repeat
		end if
	end repeat
	
	repeat while endIndex ≥ startIndex
		set currentChar to character endIndex of textValue
		if currentChar is in whitespaceChars then
			set endIndex to endIndex - 1
		else
			exit repeat
		end if
	end repeat
	
	if startIndex > endIndex then
		return ""
	else
		return text startIndex thru endIndex of textValue
	end if
end trim_whitespace

on message_fragment(msg, mailboxName)
	using terms from application "Mail"
		set subjectText to my safe_text(subject of msg)
		set senderText to my safe_text(sender of msg)
		set idText to my safe_text(message id of msg)
		set dateText to my safe_text(date received of msg as string)
		set bodyText to my safe_text(content of msg as text)
		set toRecipientsJSON to my recipients_json(to recipients of msg)
		set ccRecipientsJSON to my recipients_json(cc recipients of msg)
	end using terms from
	set mailboxText to my safe_text(mailboxName)
	
	set fragment to "{"
	set fragment to fragment & "\"subject\":\"" & subjectText & "\""
	set fragment to fragment & ",\"date_received\":\"" & dateText & "\""
	set fragment to fragment & ",\"sender\":\"" & senderText & "\""
	set fragment to fragment & ",\"message_id\":\"" & idText & "\""
	set fragment to fragment & ",\"mailbox\":\"" & mailboxText & "\""
	set fragment to fragment & ",\"to_recipients\":" & toRecipientsJSON
	set fragment to fragment & ",\"cc_recipients\":" & ccRecipientsJSON
	if bodyText is not "" then
		set fragment to fragment & ",\"body\":\"" & bodyText & "\""
	end if
	set fragment to fragment & "}"
	return fragment
end message_fragment

on safe_text(candidate)
	if candidate is missing value then return ""
	return my escape_json(candidate as text)
end safe_text

on raw_text(candidate)
	if candidate is missing value then return ""
	return candidate as text
end raw_text

on recipient_label(rcpt)
	using terms from application "Mail"
		set nameText to my raw_text(name of rcpt)
		set addressText to my raw_text(address of rcpt)
	end using terms from
	if addressText is "" then return nameText
	if nameText is "" then return addressText
	return nameText & " <" & addressText & ">"
end recipient_label

on recipients_json(rcptList)
	if rcptList is missing value then return "[]"
	if rcptList is {} then return "[]"
	set entries to {}
	repeat with rcpt in rcptList
		set label to my recipient_label(rcpt)
		if label is not "" then
			set safeLabel to my safe_text(label)
			if safeLabel is not "" then set end of entries to "\"" & safeLabel & "\""
		end if
	end repeat
	if entries is {} then return "[]"
	set AppleScript's text item delimiters to ","
	set joined to entries as text
	set AppleScript's text item delimiters to ""
	return "[" & joined & "]"
end recipients_json

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

on sort_messages(msgList)
	set sortedList to msgList
	set itemCount to count of sortedList
	if itemCount ≤ 1 then return sortedList
	
	repeat with i from 2 to itemCount
		set currentMessage to item i of sortedList
		using terms from application "Mail"
			set currentDate to date received of currentMessage
		end using terms from
		set j to i - 1
		repeat while j ≥ 1
			using terms from application "Mail"
				set compareDate to date received of item j of sortedList
			end using terms from
			if compareDate ≤ currentDate then exit repeat
			set item (j + 1) of sortedList to item j of sortedList
			set j to j - 1
		end repeat
		set item (j + 1) of sortedList to currentMessage
	end repeat
	return sortedList
end sort_messages
