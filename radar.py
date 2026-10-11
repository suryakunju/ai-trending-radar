name: Daily AI repo radar

on:
  schedule:
    # Main run 08:30 UTC (3:30 am Central in summer), plus two backups in case
    # GitHub skips or delays a scheduled run (it is best-effort). The guard step
    # below makes the backups do nothing once today's list exists.
    - cron: "30 8 * * *"
    - cron: "50 8 * * *"
    - cron: "10 9 * * *"
  workflow_dispatch: # lets you run it by hand from the Actions tab

permissions:
  contents: write
  issues: write

concurrency:
  group: radar
  cancel-in-progress: false

jobs:
  radar:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4

      - name: Skip if today's list already exists
        id: fresh
        run: |
          if head -1 data/trending.md 2>/dev/null | grep -q "$(date -u +%F)"; then
            echo "Today's list is already there; nothing to do."
            echo "done=1" >> "$GITHUB_OUTPUT"
          fi

      - uses: actions/setup-python@v5
        if: steps.fresh.outputs.done != '1'
        with:
          python-version: "3.12"

      - name: Build today's list
        if: steps.fresh.outputs.done != '1'
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: python radar.py

      - name: Save the results
        if: steps.fresh.outputs.done != '1'
        run: |
          git config user.name "radar-bot"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add data/
          git commit -m "Radar $(date -u +%F)" || echo "Nothing changed"
          git pull --rebase
          git push

      # If any step failed, open an issue: GitHub emails you, and the morning
      # report can name the cause instead of just "stale".
      - name: Report a failure
        if: failure()
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          gh issue create --repo "$GITHUB_REPOSITORY" \
            --title "Radar failed $(date -u +%F)" \
            --body "Run: $GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID"
