' Starts the Voice Review server hidden at Windows login.
' Installed by copying into the Startup folder (shell:startup).
' Output goes to %USERPROFILE%\VoiceReview\server.log.
Set sh = CreateObject("WScript.Shell")
script = "C:\Users\truth\legal_voice_review\listen\voice.py"
logf = sh.ExpandEnvironmentStrings("%USERPROFILE%") & "\VoiceReview\server.log"
sh.Run "cmd /c py -3.13 -I """ & script & """ serve >> """ & logf & """ 2>&1", 0, False
