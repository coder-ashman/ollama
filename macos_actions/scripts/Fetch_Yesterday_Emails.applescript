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
	
	tell application "Mail"
		set targetMailbox to mailbox "My Inbox" of account "Exchange"
		set messageList to (every message of targetMailbox whose (date received is greater than or equal to startWindow) and (date received is less than or equal to endWindow))
	end tell
	
	set fragments to {}
	set orderedMessages to my sort_messages(messageList)
	repeat with eachMessage in orderedMessages
		set end of fragments to my message_fragment(eachMessage, targetMailbox)
	end repeat
	
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
		set bodyText to my safe_text(content of msg as text)
	end using terms from
	
	set fragment to "{"
	set fragment to fragment & "\"subject\":\"" & subjectText & "\""
	set fragment to fragment & ",\"date_received\":\"" & dateText & "\""
	set fragment to fragment & ",\"sender\":\"" & senderText & "\""
	set fragment to fragment & ",\"message_id\":\"" & idText & "\""
	set fragment to fragment & ",\"read\":" & (my bool_text(readFlag))
	set fragment to fragment & ",\"mailbox\":\"" & mailboxText & "\""
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
