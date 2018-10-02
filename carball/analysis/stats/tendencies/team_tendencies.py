import math
from typing import Dict, List

import pandas as pd

from carball.analysis.stats.possession.ball_distances import BallDistanceStat
from carball.generated.api.team_pb2 import Team

from ....analysis.stats.tendencies.positional_tendencies import PositionalTendencies
from ....generated.api import game_pb2
from ....generated.api.player_pb2 import Player
from ....generated.api.stats.team_stats_pb2 import TeamStats
from ....json_parser.game import Game


position_column_names = ['pos_x', 'pos_y', 'pos_z']
MAX_CLUMP_DISTANCE = math.sqrt(8192**2 + 10240**2) / 8


class TeamTendencies(PositionalTendencies):

    def calculate_team_stat(self, team_stat_list: Dict[int, TeamStats], game: Game, proto_game: game_pb2.Game,
                            player_map: Dict[str, Player], data_frame: pd.DataFrame):
        for team in proto_game.teams:
            if len(team.player_ids) <= 1:
                # center of mass does not matter for 1s games
                continue
            player_names = [player_map[player_id.id].name for player_id in team.player_ids]
            center_of_mass = self.calculate_team_center(data_frame, player_names)
            self.get_team_tendencies(team, data_frame, center_of_mass)

            self.calculate_displacements(team, player_map, center_of_mass, data_frame)

    def calculate_team_center(self, data_frame, list_of_players) -> (pd.DataFrame, List[pd.DataFrame]):
        players = []
        for player in list_of_players:
            player_frame = data_frame[player][position_column_names]
            players.append(player_frame)

        combined = pd.concat(players)
        center_position = combined.groupby(combined.index).mean()
        return center_position

    def get_team_tendencies(self, team: Team, data_frame: pd.DataFrame, team_center: pd.DataFrame):
        self.get_tendencies(data_frame, team_center, data_frame['ball'],
                            team.is_orange, team.stats.center_of_mass.positional_tendencies,
                            self.map_player_attributes_to_predicates)

    def calculate_displacements(self, team: Team, player_map: Dict[str, Player],
                                center_of_mass: pd.DataFrame, data_frame: pd.DataFrame):
        player_distances_data_frame, player_distance_times, _\
            = BallDistanceStat.calculate_player_distance_to_location(player_map, data_frame, center_of_mass)

        average_distances = []
        for player_id in team.player_ids:
            player = player_map[player_id.id]
            average_distance_from_center = player_distances_data_frame[player.id.id].mean(skipna=True)
            self.set_player_stats(player, player_distance_times, average_distance_from_center, len(team.player_ids))

            average_distances.append(average_distance_from_center)

        team.stats.center_of_mass.average_distance_from_center = sum(average_distances) / len(average_distances)

        max_distances = player_distances_data_frame.max(axis=1)
        team.stats.center_of_mass.average_max_distance_from_center = max_distances.mean(skipna=True)

        max_distances_with_delta = pd.concat([player_distances_data_frame,
                                              data_frame['game', 'delta'].rename('delta')], axis=1)

        if len(team.player_ids) == 2:
            clump_distance = MAX_CLUMP_DISTANCE / 2
        else:
            clump_distance = MAX_CLUMP_DISTANCE

        close_frames = max_distances < clump_distance
        time_clumped = max_distances_with_delta[close_frames]['delta'].sum()
        team.stats.center_of_mass.time_clumped = time_clumped

    def set_player_stats(self, player, player_distance_times, average_distance_from_center, team_size):

        player.stats.averages.average_distance_from_center = average_distance_from_center
        player_id = player.id.id

        if team_size > 2:
            try:
                player.distance.time_closest_to_team_center = player_distance_times['closest_player'][player_id]
                player.distance.time_furthest_from_team_center = player_distance_times['furthest_player'][player_id]
            except (AttributeError, KeyError):
                player.distance.time_closest_to_team_center = 0
                player.distance.time_furthest_from_team_center = 0
