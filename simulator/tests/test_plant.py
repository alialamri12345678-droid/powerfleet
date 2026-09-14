import unittest

from simulation.ems import PowerManagementConfig, PowerManager
from simulation.plant import Breaker, Generator, GeneratorState, GridSource, Load, Plant, SolarSource, SyncLimits


def generator(name="GEN1", rated_kw=500):
    return Generator(name, rated_kw, 400, 50, 0.8, 1500, Breaker(f"{name} CB", operation_time_s=0))


def advance(plant, seconds, step=0.1, manager=None):
    for _ in range(round(seconds / step)):
        if manager:
            manager.update()
        plant.update(step)


class GeneratorTests(unittest.TestCase):
    def test_start_and_stop_sequences_take_time(self):
        gen = generator()
        plant = Plant("test", 400, 50, [gen], [])
        gen.start()
        plant.update(0.1)
        self.assertEqual(gen.state, GeneratorState.PRESTART)
        advance(plant, 13)
        self.assertEqual(gen.state, GeneratorState.RUNNING_OFF_LOAD)
        self.assertAlmostEqual(gen.rpm, 1500, places=1)
        gen.stop()
        advance(plant, 8)
        self.assertEqual(gen.state, GeneratorState.STOPPED)
        self.assertEqual(gen.rpm, 0)

    def test_failed_start(self):
        gen = generator()
        gen.fail_to_start = True
        plant = Plant("test", 400, 50, [gen], [])
        gen.start()
        advance(plant, 6)
        self.assertEqual(gen.state, GeneratorState.FAILED_TO_START)
        self.assertTrue(gen.alarms["fail_to_start"].active)

    def test_fuel_curve_interpolation(self):
        gen = generator()
        gen.fuel_curve_lph = ((0.25, 30), (0.5, 50), (0.75, 70), (1.0, 100))
        gen.transition(GeneratorState.ON_LOAD)
        gen.active_kw = 312.5
        self.assertAlmostEqual(gen._fuel_lph(), 60)


class SynchronizationTests(unittest.TestCase):
    def setUp(self):
        self.grid = GridSource(breaker=Breaker("GRID CB", state="CLOSED", feedback_closed=True, operation_time_s=0))
        self.grid.breaker.state = self.grid.breaker.state.__class__.CLOSED if hasattr(self.grid.breaker.state, '__class__') and not isinstance(self.grid.breaker.state, str) else self.grid.breaker.state

    def test_large_phase_difference_does_not_close_immediately(self):
        gen = generator()
        gen.transition(GeneratorState.RUNNING_OFF_LOAD)
        gen.rpm, gen.frequency_hz, gen.voltage_v, gen.phase_angle_deg = 1500, 50, 400, 120
        plant = Plant("test", 400, 50, [gen], [], grid=None, sync_limits=SyncLimits(minimum_stable_s=0.5))
        plant.bus_voltage_v, plant.bus_frequency_hz, plant.bus_phase_angle_deg = 400, 50, 0
        gen.begin_synchronizing()
        gen.update(0.1, 400, 50, 0, plant.sync_limits)
        self.assertFalse(gen.breaker.closed)

    def test_acceptable_sync_closes(self):
        gen = generator()
        gen.transition(GeneratorState.RUNNING_OFF_LOAD)
        gen.rpm, gen.frequency_hz, gen.voltage_v, gen.phase_angle_deg = 1500, 50.05, 398, 2
        limits = SyncLimits(minimum_stable_s=0.2)
        gen.begin_synchronizing()
        for _ in range(5):
            gen.update(0.1, 400, 50, 0, limits)
        self.assertTrue(gen.breaker.closed)

    def test_first_generator_can_close_onto_dead_bus(self):
        gen = generator()
        gen.transition(GeneratorState.RUNNING_OFF_LOAD)
        gen.rpm, gen.frequency_hz, gen.voltage_v = 1500, 50, 400
        plant = Plant("test", 400, 50, [gen], [])
        self.assertTrue(plant.close_generator_breaker(gen))
        advance(plant, 0.5)
        self.assertTrue(gen.breaker.closed)
        plant.update(0.1)
        self.assertTrue(plant.bus_energized)

    def test_opened_loaded_breaker_returns_generator_to_off_load_and_can_reclose(self):
        gen = generator()
        gen.state, gen.breaker.state, gen.breaker.feedback_closed = GeneratorState.ON_LOAD, gen.breaker.state.__class__.CLOSED, True
        gen.active_kw = gen.target_kw = 300
        plant = Plant("test", 400, 50, [gen], [])
        gen.breaker.request_open(); gen.update(0.1, 0, 0, 0, plant.sync_limits)
        self.assertEqual(gen.state, GeneratorState.RUNNING_OFF_LOAD)
        self.assertEqual(gen.active_kw, 0)
        self.assertTrue(plant.close_generator_breaker(gen))


class SharingTests(unittest.TestCase):
    def test_equal_generators_share_equally(self):
        gens = [generator("G1"), generator("G2")]
        for gen in gens:
            gen.state, gen.breaker.state, gen.breaker.feedback_closed = GeneratorState.ON_LOAD, gen.breaker.state.__class__.CLOSED, True
        plant = Plant("test", 400, 50, gens, [])
        plant.share_generator_load(600)
        self.assertEqual([g.target_kw for g in gens], [300, 300])

    def test_unequal_generators_share_proportionally(self):
        gens = [generator("G1", 1000), generator("G2", 500)]
        for gen in gens:
            gen.state, gen.breaker.state, gen.breaker.feedback_closed = GeneratorState.ON_LOAD, gen.breaker.state.__class__.CLOSED, True
        plant = Plant("test", 400, 50, gens, [])
        plant.share_generator_load(900)
        self.assertEqual([g.target_kw for g in gens], [600, 300])

    def test_reactive_load_is_shared_by_kva_rating(self):
        gens = [generator("G1", 1000), generator("G2", 500)]
        for gen in gens:
            gen.state, gen.breaker.state, gen.breaker.feedback_closed = GeneratorState.ON_LOAD, gen.breaker.state.__class__.CLOSED, True
        plant = Plant("test", 400, 50, gens, [])
        plant.share_reactive_load(450)
        self.assertEqual([g.target_kvar for g in gens], [300, 150])

    def test_manual_kw_setpoint_is_kept_while_other_generator_shares_remainder(self):
        gens = [generator("G1", 1000), generator("G2", 500)]
        for gen in gens:
            gen.state, gen.breaker.state, gen.breaker.feedback_closed = GeneratorState.ON_LOAD, gen.breaker.state.__class__.CLOSED, True
        gens[0].load_mode, gens[0].fixed_kw_setpoint = "fixed_kw", 400
        plant = Plant("test", 400, 50, gens, [])
        plant.share_generator_load(700)
        self.assertEqual([g.target_kw for g in gens], [400, 300])

    def test_breaker_control_is_manual_by_default_and_optional_in_auto(self):
        gen = generator()
        gen.transition(GeneratorState.RUNNING_OFF_LOAD)
        gen.rpm, gen.frequency_hz, gen.voltage_v = 1500, 50, 400
        plant = Plant("test", 400, 50, [gen], [])
        PowerManager(plant).update()
        self.assertFalse(gen.breaker.closed)
        manager = PowerManager(plant, PowerManagementConfig(automatic_start_stop=False, automatic_breaker_control=True))
        manager.update(); gen.breaker.update(1)
        self.assertTrue(gen.breaker.closed)


class LoadTests(unittest.TestCase):
    def test_step_and_motor_start_events(self):
        load = Load("motor", 100, power_factor=.8)
        load.trigger_step(20)
        load.trigger_motor_start(duration_s=2, multiplier=5)
        self.assertEqual(load.demand(__import__("random").Random(1))[0], 600)
        load.update(2)
        self.assertEqual(load.demand(__import__("random").Random(1))[0], 120)


class GridSolarTests(unittest.TestCase):
    def test_grid_failure_and_restoration(self):
        grid = GridSource(breaker=Breaker("GRID CB", operation_time_s=0))
        grid.breaker.request_close(); grid.breaker.update(1)
        plant = Plant("test", 400, 50, [], [Load("load", 100)], grid=grid)
        plant.update(0.1)
        self.assertTrue(plant.bus_energized)
        grid.available = False
        plant.update(0.1); grid.breaker.update(1); plant.update(0.1)
        self.assertFalse(plant.bus_energized)
        grid.available, grid.voltage_v, grid.frequency_hz = True, 400, 50
        grid.breaker.request_close(); grid.breaker.update(1); plant.update(0.1)
        self.assertTrue(plant.bus_energized)

    def test_grid_following_solar_requires_bus_and_obeys_curtailment(self):
        solar = SolarSource("PV", 500, Breaker("PV CB", operation_time_s=0), irradiance_pct=80, inverter_efficiency=1, ramp_kw_per_s=1000)
        solar.breaker.request_close(); solar.breaker.update(1)
        solar.curtailment_limit_kw = 250
        solar.update(1, True)
        self.assertEqual(solar.active_kw, 250)
        solar.update(1, False)
        self.assertEqual(solar.active_kw, 0)

    def test_ems_curtails_pv_for_minimum_generator_load(self):
        gen = generator(rated_kw=500)
        gen.state, gen.breaker.state, gen.breaker.feedback_closed = GeneratorState.ON_LOAD, gen.breaker.state.__class__.CLOSED, True
        solar = SolarSource("PV", 600, Breaker("PV CB"), inverter_efficiency=1)
        plant = Plant("test", 400, 50, [gen], [Load("load", 500)], solar=solar)
        PowerManager(plant).update()
        self.assertEqual(solar.curtailment_limit_kw, 350)


if __name__ == "__main__":
    unittest.main()
