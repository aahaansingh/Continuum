import numpy as np
from ortools.sat.python import cp_model

class solver :
    def __init__ (self, songs_lst, key_fn_dict, modal_pen, tempo_wt, energy_wt, target_energy_diff, threshold):
        """
        Initialize the solver with the given parameters.
        :param songs_lst: List of songs, where each song is represented as a dictionary with attributes like 'key', 'mode', 'tempo', etc.
        :param key_fn_dict: Contains the key reward function and its values for different key distances, as well as weight.
        :param modal_pen: Reward for mode change between songs.
        :param tempo_wt: Weight for tempo difference
        :param energy_wt: Weight for energy difference
        :param target_energy_diff: Target value for the weighted sum of tempo and energy differences.
        :param threshold: Maximum length of mixed playlist
        """
        self.songs_lst = songs_lst
        self.key_fn_dict = key_fn_dict
        self.modal_pen = modal_pen
        self.tempo_wt = tempo_wt
        self.energy_wt = energy_wt
        self.target_energy_diff = target_energy_diff
        self.threshold = threshold
    
    def transition_score(self, song1: dict, song2: dict):
        # We have to formulate this in terms of rewards because otherwise the solver may choose not to add a song even when it has space
        # Penalties are more logical but maximization avoids the possibility of empty playlists
        key_dist = min(abs(song1['key'] - song2['key']), 12 - abs(song1['key'] - song2['key']))
        key_reward = self.key_fn_dict['key_pen'] * self.key_fn_dict[key_dist]
        modal_reward = (1 if song1['mode'] == song2['mode'] else 0) * self.modal_pen
        tempo_reward = max(40 - abs(song1['tempo'] - song2['tempo']) * self.tempo_wt, 0)
        # Can't think of a good bound on energy penalty, so we'll just floor the total score at 0
        energy_penalty = abs((song2['energy'] - song1['energy']) * self.energy_wt + (song2['BPM'] - song1['BPM']) * self.tempo_wt - self.target_energy_diff)
        return max(key_reward + modal_reward + tempo_reward - energy_penalty, 0)
    
    def transition_mtx_score(self):
        n = len(self.songs_lst)
        mtx = [[0 for _ in range(n)] for _ in range(n)]
        for i in range(n):
            for j in range(n):
                if i != j:
                    mtx[i][j] = self.transition_score(self.songs_lst[i], self.songs_lst[j])
        return np.ndarray(mtx)

    def encode_albums(self):
        album_id_map = {}
        album_ids = np.empty(len(self.songs_lst), dtype=int)
        song_ids = []

        next_id = 0
        for i, song in enumerate(self.songs_lst):
            key = (song.get('artist'), song.get('album'))
            song_ids.append(song.get('id'))

            if key not in album_id_map:
                album_id_map[key] = next_id
                next_id += 1

            album_ids[i] = album_id_map[key]

        return album_id_map, album_ids, song_ids


    def solve(self, time_limit_sec=10):
        c = self.transition_mtx_score()
        w = np.array([song.get('duration_ms', 0) for song in self.songs_lst])
        _, k, song_ids = self.encode_albums()
        
        n = len(w)
        model = cp_model.CpModel()

        # Variables
        x = {}
        for u in range(n):
            for v in range(n):
                if u != v:
                    x[u, v] = model.NewBoolVar(f"x_{u}_{v}")

        y = [model.NewBoolVar(f"y_{v}") for v in range(n)]

        # Order variables (MTZ)
        order = [model.NewIntVar(0, n, f"order_{v}") for v in range(n)]

        # --------------------
        # Degree constraints
        # --------------------
        for v in range(n):
            model.Add(
                sum(x[u, v] for u in range(n) if u != v) <= y[v]
            )
            model.Add(
                sum(x[v, u] for u in range(n) if u != v) <= y[v]
            )

        # At most one start and one end
        model.Add(
            sum(y[v] - sum(x[u, v] for u in range(n) if u != v) for v in range(n)) <= 1
        )
        model.Add(
            sum(y[v] - sum(x[v, u] for u in range(n) if u != v) for v in range(n)) <= 1
        )

        # --------------------
        # Budget constraint
        # --------------------
        model.Add(sum(w[v] * y[v] for v in range(n)) <= self.threshold)

        # --------------------
        # Color constraint
        # --------------------
        colors = set(k)
        for color in colors:
            model.Add(
                sum(y[v] for v in range(n) if k[v] == color) <= 1
            )

        # --------------------
        # Subtour elimination (MTZ)
        # --------------------
        for u in range(n):
            for v in range(n):
                if u != v:
                    model.Add(order[v] >= order[u] + 1).OnlyEnforceIf(x[u, v])

        # If node is unused, order is zero
        for v in range(n):
            model.Add(order[v] == 0).OnlyEnforceIf(y[v].Not())

        # --------------------
        # Objective
        # --------------------
        model.Maximize(
            sum(c[u, v] * x[u, v] for (u, v) in x)
        )

        # --------------------
        # Solve
        # --------------------
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_sec
        solver.parameters.num_search_workers = 8

        status = solver.Solve(model)

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None

        # --------------------
        # Extract solution
        # --------------------
        used_nodes = [v for v in range(n) if solver.Value(y[v])]
        used_edges = [(u, v) for (u, v) in x if solver.Value(x[u, v])]

        # Sort used_nodes based on order
        used_nodes.sort(key=lambda v: solver.Value(order[v]))

        return {
            "objective": solver.ObjectiveValue(),
            "nodes": used_nodes,
            "edges": used_edges,
            "order": {v: solver.Value(order[v]) for v in used_nodes},
            "song_ids": [song_ids[v] for v in used_nodes]
        }

