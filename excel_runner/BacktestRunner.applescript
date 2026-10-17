on RunShell(commandText)
	with timeout of 36000 seconds
		do shell script commandText
		return result
	end timeout
end RunShell

on OpenPath(pathText)
	do shell script "open " & quoted form of pathText
	return ""
end OpenPath
