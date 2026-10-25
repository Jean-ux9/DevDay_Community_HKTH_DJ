-- Static source. Values arrive only as argv; never compile user content.
-- Reference: Apple Mail automation; send targets the result of this make only.
on run argv
    set dispatchStarted to false
    try
        if (count of argv) is not 4 then return "GAZE_MAIL_PRE_SEND_FAILED"
        set exactRecipient to item 1 of argv
        set exactSubject to item 2 of argv
        set exactBody to item 3 of argv
        set exactSender to item 4 of argv
        tell application "Mail"
            -- Validate only the supplied sender; never silently use another account.
            set senderAccounts to every account whose email addresses contains exactSender
            if (count of senderAccounts) is 0 then return "GAZE_MAIL_NO_ACCOUNT"
            if (count of senderAccounts) is not 1 then return "GAZE_MAIL_PRE_SEND_FAILED"
            if (enabled of item 1 of senderAccounts) is not true then return "GAZE_MAIL_NO_ACCOUNT"
            set newDraft to make new outgoing message with properties {visible:false, subject:exactSubject}
            set sender of newDraft to exactSender
            set message signature of newDraft to missing value
            set content of newDraft to exactBody
            tell newDraft
                make new to recipient at end of to recipients with properties {address:exactRecipient}
            end tell
            -- Inspect only the object just created, never existing drafts/inbox/AX.
            if (count of to recipients of newDraft) is not 1 then return "GAZE_MAIL_PRE_SEND_FAILED"
            if (count of cc recipients of newDraft) is not 0 then return "GAZE_MAIL_PRE_SEND_FAILED"
            if (count of bcc recipients of newDraft) is not 0 then return "GAZE_MAIL_PRE_SEND_FAILED"
            if (address of first to recipient of newDraft) is not exactRecipient then return "GAZE_MAIL_PRE_SEND_FAILED"
            if (sender of newDraft) is not exactSender then return "GAZE_MAIL_PRE_SEND_FAILED"
            if (subject of newDraft) is not exactSubject then return "GAZE_MAIL_PRE_SEND_FAILED"
            set dispatchStarted to true
            set accepted to send newDraft
            if accepted is true then return "GAZE_MAIL_ACK"
        end tell
        return "GAZE_MAIL_UNKNOWN"
    on error errorText number errorNumber
        -- Never emit the error text: it may contain a destination or body.
        if dispatchStarted then return "GAZE_MAIL_UNKNOWN"
        if errorNumber is -1743 then return "GAZE_MAIL_PERMISSION"
        return "GAZE_MAIL_PRE_SEND_FAILED"
    end try
end run
