### Prerequisites:
- Python
- install requirements.txt
- ngrok
- Azure bot resource ([Tutorial](https://learn.microsoft.com/en-us/microsoftteams/platform/sbs-teams-conversation-bot?tabs=ngrok))
### Steps:
1. clone the repo.
2. run `python app.py`
3. run the `ngrok_proxy` script and note the url.
4. Change the Messaging endpoint (change it to the url you got from previous step) in Configuration settings of Bot Resource from [Azure Portal](https://portal.azure.com/)
5. Open the `teamsAppManifest` directory and compress its contents in an archive.
6. Load this archive as a bot in MSTeams.

