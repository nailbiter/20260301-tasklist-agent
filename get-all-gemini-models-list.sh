#!/bin/sh
curl "https://generativelanguage.googleapis.com/v1beta/models?key=$GEMINI_API_KEY"|jq
