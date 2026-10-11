name: Update stats

on:
workflow_dispatch:
schedule:
- cron: ‘0,30 0-23 1-31 1-12 0-6’

permissions:
contents: write

jobs:
update:
runs-on: ubuntu-latest
steps:
- uses: actions/checkout@v4
- uses: actions/setup-python@v5
with:
python-version: ‘3.11’
- run: pip install requests
- name: Run script
env:
DISCORD_BOT_TOKEN: ${{ secrets.DISCORD_BOT_TOKEN }}
DISCORD_STATS_CHANNEL_ID: ${{ secrets.DISCORD_STATS_CHANNEL_ID }}
run: python update_stats.py
- name: Save data
run: |
cat data.json
git config user.name “github-actions”
git config user.email “actions@github.com”
git add data.json
git diff --staged --quiet || git commit -m “Update stats”
git push
