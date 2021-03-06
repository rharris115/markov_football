from .markov_football import *
from collections import deque
from itertools import islice


def generate_random_player_population(n: int = 1) -> Iterable[Player]:
    ng = NamesGenerator.names(n=n)
    multiplier = np.random.uniform(0.0, 2.0)
    for i in range(n):
        abilities = Abilities(
            {ability: multiplier * value for ability, value in zip(Ability, np.random.uniform(low=0.0, high=1.0,
                                                                                              size=len(Ability)))})
        player = Player(name=next(ng), age=16, abilities=abilities)
        yield player


def generate_typical_player_population(n: int = 1, typical: float = 0.5) -> Iterable[Player]:
    ng = NamesGenerator.names(n=n)
    for i in range(n):
        abilities = Abilities(
            {ability: typical for ability in Ability})
        player = Player(name=next(ng), age=16, abilities=abilities)
        yield player


def create_selection(name: str, players: Iterable[Player]) -> Selection:
    return Selection(name=name,
                     players=[(next(players), Position.B) for i in range(6)] +
                             [(next(players), Position.GK)] +
                             [(next(players), Position.D) for i in range(4)] +
                             [(next(players), Position.M) for i in range(4)] +
                             [(next(players), Position.F) for i in range(2)])


def optmise_player_positions_in_parrallel(
        selections: Iterable[Selection],
        team_states: Iterable[TeamState],
        max_cycles_without_improvement: int = 100) -> Iterable[Selection]:
    local_selections_by_name = {selection.name: selection for selection in selections}
    names = [selection.name for selection in selections]

    cycles_without_improvement = 0

    while cycles_without_improvement < max_cycles_without_improvement:

        for name in names:
            selection = local_selections_by_name[name]

            next_goal_p = sum(
                evaluate_selection(selection=selection,
                                   reference_selections=local_selections_by_name.values(),
                                   team_states=team_states)) / len(local_selections_by_name)

            trial_next_goal_p, trial_selection, description = _experiment_with_positioning(selection=selection,
                                                                                           reference_selections=local_selections_by_name.values(),
                                                                                           team_states=team_states)

            if not trial_selection:
                continue
            elif trial_next_goal_p > next_goal_p:
                local_selections_by_name[name] = trial_selection
                logger.info('Change by %s: %s' % (name, description))
                cycles_without_improvement = 0
        cycles_without_improvement += 1
    for name in names:
        yield local_selections_by_name[name]


def _experiment_with_positioning(selection: Selection,
                                 reference_selections: Iterable[Selection],
                                 team_states: Iterable[TeamState]) -> Tuple[float, Selection, str]:
    if np.random.choice(a=[True, False]):
        player = np.random.choice(a=list(selection.keys()))
        old_position = selection[player]
        new_position = np.random.choice(a=[pos for pos in Position if pos is not old_position])
        description = 'Move %s from %s to %s.' % (str(player.name), old_position.name, new_position.name)
        try:
            new_selection = selection.with_player_positions(player_positions=[(player, new_position)])
        except:
            return (0, None, description)
    else:
        player1, player2 = np.random.choice(a=list(selection.keys()),
                                            size=2,
                                            replace=False)
        position1, position2 = selection[player1], selection[player2]
        description = 'Swap %s in %s for %s in %s.' % (
            str(player1.name), position1.name, str(player2.name), position2.name)
        if position1 is position2:
            return (0, None, description)
        try:
            new_selection = selection.with_player_positions(
                player_positions=[(player1, position2), (player2, position1)])
        except:
            return (0, None, description)

    next_goal_probs = list(evaluate_selection(selection=new_selection,
                                              reference_selections=reference_selections,
                                              team_states=team_states))

    new_next_goal_prob = sum(next_goal_probs) / len(next_goal_probs)
    return new_next_goal_prob, new_selection, description


def evaluate_selection(
        selection: Selection,
        reference_selections: Iterable[Selection],
        team_states: Iterable[TeamState]) -> Iterable[float]:
    for reference_selection in reference_selections:
        if reference_selection.name is selection.name:
            yield 0.5
            continue

        ngps = next_goal_probs(mc=calculate_markov_chain(selection_1=selection,
                                                         selection_2=reference_selection),
                               team_states=team_states)
        next_goal_prob = ngps[S(selection.name, TeamState.SCORED)]
        yield next_goal_prob


def create_next_goal_matrix(selections: List[Selection], team_states: Iterable[TeamState]) -> pd.DataFrame:
    names = [selection.name for selection in selections]
    n = len(names)
    A = np.zeros(shape=(n, n))

    mean_probability_other_selection = list()

    for row_index, selection in enumerate(selections):
        probs = list(evaluate_selection(selection=selection,
                                        reference_selections=selections,
                                        team_states=team_states))
        A[row_index, :] = probs

        mean_probability_other_selection.append(
            sum([prob for col_index, prob in enumerate(probs) if col_index != row_index]) / (n - 1))

    frame = pd.DataFrame(data=pd.DataFrame(A, index=names, columns=names))
    frame['mean'] = pd.Series(mean_probability_other_selection, index=frame.index)

    frame.sort_values(['mean'], inplace=True, ascending=False)

    cols = frame.columns.tolist()
    cols = cols[-1:] + cols[:-1]
    frame = frame[cols]

    return frame


def fixtures(teams: Iterable[str]) -> Iterable[List[str]]:
    teams = list(teams)
    if len(teams) % 2:
        teams.append(None)

    ln = len(teams) // 2
    dq1, dq2 = deque(islice(teams, None, ln)), deque(islice(teams, ln, None))
    for _ in range(len(teams) - 1):
        yield list(zip(dq1, dq2))  # list(zip.. python3
        #  pop off first deque's left element to
        # "fix one of the competitors in the first column"
        start = dq1.popleft()
        # rotate the others clockwise one position
        # by swapping elements
        dq1.appendleft(dq2.popleft())
        dq2.append(dq1.pop())
        # reattach first competitor
        dq1.appendleft(start)


def hold_fixture(selection_1: Selection, selection_2: Selection):
    selection_1, selection_2 = optmise_player_positions_in_parrallel(
        selections=(selection_1, selection_2),
        team_states=[TeamState.WITH_M])

    mc = calculate_markov_chain(selection_1=selection_1, selection_2=selection_2)

    score_keeper = Counter()
    s = S(selection_1.name, TeamState.WITH_M)
    for step in range(100):
        next_s = mc.simulate_next(s)

        if next_s == S(selection_1.name, TeamState.SCORED):
            score_keeper.update([selection_1.name])
            s = S(selection_2.name, TeamState.WITH_M)
        elif next_s == S(selection_2.name, TeamState.SCORED):
            score_keeper.update([selection_2.name])
            s = S(selection_1.name, TeamState.WITH_M)
        else:
            s = next_s

    return score_keeper


def display_league(lineups_by_name: Dict[str, List[Selection]]):
    table = create_next_goal_matrix(lineups_by_name.values(), team_states=[TeamState.WITH_M])
    mean_table = table.loc[:, ['mean']]

    player_counts_by_position_list = [
        {position: len(players)
         for position, players in lineups_by_name[lineup_name].formation().items()}
        for lineup_name in mean_table.index
    ]

    for position in Position:
        mean_table[position.name] = pd.Series([player_counts_by_position[position]
                                               for player_counts_by_position in
                                               player_counts_by_position_list], index=mean_table.index)

    print(mean_table)


def hold_week(fixtures: List[Tuple[str, str]], selections_by_name: Dict[str, Selection],
              player_position_history: Dict[str, List[Position]], goals: Counter, conceded_goals: Counter,
              points: Counter, wins: Counter, losses: Counter, draws: Counter):
    for club_1, club_2 in fixtures:
        print('%s vs. %s' % (club_1, club_2))

        if not club_1 or not club_2:
            continue

        selection_1 = selections_by_name[club_1]
        selection_2 = selections_by_name[club_2]

        selection_1, selection_2 = optmise_player_positions_in_parrallel(
            selections=(selection_1, selection_2),
            team_states=[TeamState.WITH_M])

        for selection in [selection_1, selection_2]:
            for player, position in selection.items():
                player_position_history[player.name].append(position)

        selections_by_name[club_1] = selection_1
        selections_by_name[club_2] = selection_2

        display_league(lineups_by_name={club_1: selection_1,
                                        club_2: selection_2})

        score_keeper = hold_fixture(selection_1=selection_1, selection_2=selection_2)

        goals.update(score_keeper)
        conceded_goals[club_1] += score_keeper[club_2]
        conceded_goals[club_2] += score_keeper[club_1]

        if score_keeper[club_1] > score_keeper[club_2]:
            points[club_1] += 3
            wins[club_1] += 1
            losses[club_2] += 1
        elif score_keeper[club_2] > score_keeper[club_1]:
            points[club_2] += 3
            wins[club_2] += 1
            losses[club_1] += 1
        else:
            points[club_1] += 1
            points[club_2] += 1
            draws[club_1] += 1
            draws[club_2] += 1

        print()
        print('%s: %d\t%s: %d' % (club_1, score_keeper[club_1], club_2, score_keeper[club_2]))
        print()
        print()
