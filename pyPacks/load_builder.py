""" Loading logic
 - Group undelivered packages by location and availability
 - Pick the farthest package from the hub with achievable constraints and the earliest deadline
 - Find nearest neighbor groups until truck is full (nearest-neighbor should use a heap)
 - - Make sure no location is partially loaded on a truck
 - Once truck is full, add "return to hub" to location node list and optimize

"""
from itertools import groupby
from typing import List, Set
from model.package_group import PackageGroup
from model.package import Package, PackageStatus
from model.routing_table import RoutingTable
from model.truck import Truck
from model.location import Location


class LoadBuilder(object):

    def __init__(self, locations, packages, trucks, routing_table: RoutingTable):
        self.locations = locations
        self.packages = packages
        self.package_groups = self.group_packages(packages)
        self.build_pg_object_links(self.package_groups)

        self.trucks = trucks
        self.routing_table = routing_table

    @staticmethod
    def group_packages(packages):
        """Group undelivered packages by location and availability."""
        # Group package by location and status
        keyfunc = lambda x: str(x.dest_location.loc_id) + "-" + x.status.value
        sorted_packs = sorted(packages, key=keyfunc)
        grouped_packs = groupby(sorted_packs, keyfunc)

        # Turn Grouper objects into PackageGroups
        package_groups = []
        for k, v in grouped_packs:
            this_pg = PackageGroup(list(v))
            package_groups.append(this_pg)
            # print(f"Location {k} has {sum(1 for x in this_pg.packages)} packages")
        return package_groups

    @staticmethod
    def build_pg_object_links(package_groups: List[PackageGroup]):
        for pg in package_groups:
            # Forward links
            link_ids = pg.get_linked_package_ids()
            for a_linked_id in link_ids:
                linked_pg = PackageGroup.get_owning_package_group(a_linked_id)
                pg.linked_package_groups.add(linked_pg)  # Forward
                linked_pg.linked_package_groups.add(pg)  # Reverse

    def choose_starting_group(self) -> PackageGroup:
        """Pick the farthest unconstrained package from the hub, prioritizing earlier deadlines."""
        # TODO: Add priority for packages with early deliver deadlines
        return self.get_available_prioritized()[0]

    def get_available_prioritized(self) -> List[PackageGroup]:
        """The order packages should be picked up in current conditions."""
        available_packages = [x for x in self.package_groups if x.get_status() == PackageStatus.READY_FOR_PICKUP]
        # Packages due soonest, preferring farther from hub
        sorted_pgs = sorted(available_packages, key=lambda x:
        x.get_remaining_time() - self.routing_table.lookup(1, x.destination.loc_id) / 100)
        return sorted_pgs

    def determine_truckload(self, truck: Truck):
        """Loads a truck's worth of packages.
        Starts with farthest valid package and picks nearest neighbors from there until full."""
        # TODO: Seriously, prioritize package groups with deadlines
        # TODO: New linked package logic makes for horrible routing
        location_skip_list: List[Location] = []  # Locations that need too many packages delivered to fit in what's left
        last = self.choose_starting_group()

        while truck.get_package_count() < truck.package_capacity:
            # Find the next nearest place that needs a delivery
            # valid_locations is available_pgroups less already loaded locations
            valid_locations = \
                [pg.destination for pg in self.get_available_prioritized()
                 if pg.destination not in truck.get_locations_on_route() and pg.destination not in location_skip_list]
            if truck.get_package_count() == 0:
                nn_loc = last.destination
            else:
                try:
                    nn_loc: Location = self.routing_table.get_nearest_neighbor_of_set(last.destination, valid_locations)
                except ValueError:
                    print("No more packages available for this truck at this time.")
                    break
            nn_pg: PackageGroup = [x for x in self.get_available_prioritized() if x.destination == nn_loc][0]

            # Check for linked packages/groups
            linked_pgs = nn_pg.get_linked_package_groups()

            linked_count = sum([x.get_count() for x in linked_pgs])
            if len(linked_pgs) > 1:
                print(f"Attempting to load {linked_count} linked packages: {linked_pgs}...")

            # Check to see if this PackageGroup will fit
            can_fit = truck.get_package_count() + linked_count <= truck.package_capacity
            allowed_on_truck = len(nn_pg.packages[0].valid_truck_ids) == 0 or \
                               truck.truck_num in nn_pg.packages[0].valid_truck_ids
            if can_fit and allowed_on_truck:  # Allowed to be on this truck
                for pg in linked_pgs:
                    if pg not in truck.package_groups:
                        truck.load_package_group(pg)
                    location_skip_list.append(pg.destination)
                last = nn_pg
                if len(linked_pgs) > 1:
                    print(f"Successfully loaded {linked_count} linked packages.")
            else:
                location_skip_list.append(nn_loc)  # Bypass this location next time

        # ----------------------------------------------

        # Determine rough stats using load-order routing.
        locations = [x.destination for x in truck.package_groups]

        # Must start and end at hub
        locations.insert(0, self.locations[0])
        locations.append(self.locations[0])
        
        i = 0
        distances: List[float] = []
        while i < (len(locations) - 1):
            distances.append(self.routing_table.lookup(locations[i].loc_id, locations[i + 1].loc_id))
            i += 1
        total = sum(distances)
        ids_string = ', '.join([str(x) for x in sorted(truck.get_loaded_ids())])
        print("Final loaded IDs: " + ids_string)
        # print("Distances:", distances)
        # print(f"Total miles: {total:.1f}")

        truck.determine_route()
        return truck.get_loaded_ids()

    # TODO: Create method for optimizing routes.
