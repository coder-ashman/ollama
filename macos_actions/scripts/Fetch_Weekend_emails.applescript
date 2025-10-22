use AppleScript version "2.8"
use scripting additions

on run
	return my collect_weekend_messages()
end run

on collect_weekend_messages()
	set todayDate to current date
	set time of todayDate to 0
	set cursorDate to todayDate
	repeat while (weekday of cursorDate is not Friday)
		set cursorDate to cursorDate - 1 * days
	end repeat
	set startWindow to cursorDate
	set endWindow to cursorDate + 3 * days - 1
	
	set folderNames to {}
	set messageBatches to {}
	
	tell application "Mail"
		set exchangeAccount to account "Exchange"
		set parentMailbox to mailbox "My Inbox" of exchangeAccount
		repeat with folderLabel in {"Rajesh Jayaraj", "Cassie Pizzurro"}
			try
				set childMailbox to mailbox folderLabel of parentMailbox
				set end of folderNames to (name of childMailbox as text)
				set msgList to (every message of childMailbox whose (date received is greater than or equal to startWindow) and (date received is less than or equal to endWindow))
				set end of messageBatches to msgList
			on error
				-- subfolder missing; skip
			end try
		end repeat
		set end of folderNames to (name of parentMailbox as text)
		set msgList to (every message of parentMailbox whose (date received is greater than or equal to startWindow) and (date received is less than or equal to endWindow))
		set end of messageBatches to msgList
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
	
	return "{\"messages\":[" & joined & "]}"
end collect_weekend_messages

on message_fragment(msg, mailboxName)
	using terms from application "Mail"
		set subjectText to my safe_text(subject of msg)
		set senderText to my safe_text(sender of msg)
		set idText to my safe_text(message id of msg)
		set readFlag to read status of msg
		set dateText to my safe_text(date received of msg as string)
		set bodyText to my safe_text(content of msg as text)
	end using terms from
	set mailboxText to my safe_text(mailboxName)
	
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
