-- Static source. Values arrive only as argv; never compile user content.
-- Sends through the single enabled iMessage account only (no SMS, no other account).
on run argv
    set dispatchStarted to false
    try
        if (count of argv) is not 2 then return "GAZE_MSG_PRE_SEND_FAILED"
        set exactRecipient to item 1 of argv
        set exactBody to item 2 of argv
        tell application "Messages"
            set imessageAccounts to every account whose service type is iMessage and enabled is true
            if (count of imessageAccounts) is 0 then return "GAZE_MSG_NO_ACCOUNT"
            if (count of imessageAccounts) is not 1 then return "GAZE_MSG_PRE_SEND_FAILED"
            set targetParticipant to participant exactRecipient of (item 1 of imessageAccounts)
            set dispatchStarted to true
            send exactBody to targetParticipant
        end tell
        return "GAZE_MSG_ACK"
    on error errorText number errorNumber
        -- Never emit the error text: it may contain a destination or body.
        if dispatchStarted then return "GAZE_MSG_UNKNOWN"
        if errorNumber is -1743 then return "GAZE_MSG_PERMISSION"
        return "GAZE_MSG_PRE_SEND_FAILED"
    end try
end run
