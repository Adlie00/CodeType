with open('D:\CODETYPE\game\constants.py', 'r') as f:
    content = f.read()

if 'TOURNAMENT_NAME' not in content:
    with open('D:\CODETYPE\game\constants.py', 'a') as f:
        f.write('\n# Tournament constants\n')
        f.write('TOURNAMENT_NAME = "TOURNAMENT"\n')
        f.write('TOURNAMENT_TEAM_COUNT = 5\n')
        f.write('TOURNAMENT_PLAYERS_PER_TEAM = 5\n')
        f.write('TOURNAMENT_TEAM_NUMBERS = (1, 2, 3, 4, 5)\n')
        f.write('TOURNAMENT_PLAYER_NUMBERS = (1, 2, 3, 4, 5)\n')
        f.write('TOURNAMENT_DIFFICULTY = DIFFICULTY_EASY\n')
        f.write('TOURNAMENT_RESULTS_FILE = os.path.join(DATABASE_DIR, "tournament_results.csv")\n')
    print('Added tournament constants')
else:
    print('Already present')
