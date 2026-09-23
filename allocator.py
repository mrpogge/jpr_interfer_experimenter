import random

class BlockRandomiser:

    def __init__(self):
        self.block = []

    def restore(self, block):
        self.block = list(block)

    def get_next_group(self):
        if not self.block:
            self.block = ["A", "A", "P", "P"]
            random.shuffle(self.block)

        return self.block.pop()

class DesignRandomiser:
    """Draws one of the N_DESIGNS pre-generated design_ids (material/design_trials.csv)
    per participant, without replacement per group — each design is used once for an
    active (A) and once for a passive (P) participant."""

    def __init__(self):
        self.pending = {"A": [], "P": []}

    def restore(self, group, pending):
        self.pending[group] = list(pending)

    def get_next_design(self, group):
        if not self.pending[group]:
            raise ValueError(f"No designs remaining for group {group!r}.")

        return self.pending[group].pop()

group_randomiser = BlockRandomiser()
design_randomiser = DesignRandomiser()

def allocate():
    group = group_randomiser.get_next_group()
    design_id = design_randomiser.get_next_design(group)

    return group, design_id


def restore_group_block(block):
    group_randomiser.restore(block)


def get_pending_group_block():
    return group_randomiser.block.copy()


def restore_design_pool(group, pending):
    design_randomiser.restore(group, pending)


def get_pending_design_pool(group):
    return design_randomiser.pending[group].copy()

