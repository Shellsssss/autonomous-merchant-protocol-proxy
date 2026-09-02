import time
import pytest
from app.core.inventory import (
    InMemoryInventory,
    InventoryError,
)

SKU = "LAPTOP-PRO-01"

def create_inventory(
    quantity: int = 5,
    ttl: int = 60,
):
    return InMemoryInventory(
        initial_inventory={
            SKU: quantity,
        },
        hold_ttl_seconds=ttl,
    )

def test_inventory_starts_with_expected_quantity():
    inventory = create_inventory(5)
    assert inventory.get_available_quantity(SKU) == 5

def test_create_hold_reduces_available_inventory():
    inventory = create_inventory(5)
    hold = inventory.create_hold(
        transaction_id="txn_001",
        sku=SKU,
        quantity=2,
    )

    assert hold.state == "HELD"
    assert hold.sku == SKU
    assert hold.quantity == 2
    assert inventory.get_available_quantity(SKU) == 3

def test_hold_token_is_unique():
    inventory = create_inventory(5)
    hold_1 = inventory.create_hold(
        transaction_id="txn_001",
        sku=SKU,
        quantity=1,
    )

    hold_2 = inventory.create_hold(
        transaction_id="txn_002",
        sku=SKU,
        quantity=1,
    )

    assert hold_1.hold_token != hold_2.hold_token

def test_insufficient_inventory_is_rejected():
    inventory = create_inventory(1)
    with pytest.raises(InventoryError) as exc:
        inventory.create_hold(
            transaction_id="txn_001",
            sku=SKU,
            quantity=2,
        )
    assert exc.value.code == "INSUFFICIENT_INVENTORY"

def test_commit_hold_keeps_inventory_reserved():
    inventory = create_inventory(5)
    hold = inventory.create_hold(
        transaction_id="txn_001",
        sku=SKU,
        quantity=2,
    )

    inventory.commit_hold(hold.hold_token)
    assert hold.state == "COMMITTED"
    assert inventory.get_available_quantity(SKU) == 3

def test_release_hold_returns_inventory():
    inventory = create_inventory(5)
    hold = inventory.create_hold(
        transaction_id="txn_001",
        sku=SKU,
        quantity=2,
    )
    assert inventory.get_available_quantity(SKU) == 3

    inventory.release_hold(hold.hold_token)
    assert hold.state == "RELEASED"
    assert inventory.get_available_quantity(SKU) == 5

def test_expired_hold_returns_inventory():
    inventory = create_inventory(
        quantity=5,
        ttl=1,
    )

    hold = inventory.create_hold(
        transaction_id="txn_001",
        sku=SKU,
        quantity=2,
    )
    assert inventory.get_available_quantity(SKU) == 3

    time.sleep(1.1)
    retrieved = inventory.get_hold(
        hold.hold_token
    )
    assert retrieved.state == "EXPIRED"
    assert inventory.get_available_quantity(SKU) == 5

def test_expired_hold_cannot_be_committed():
    inventory = create_inventory(
        quantity=5,
        ttl=1,
    )

    hold = inventory.create_hold(
        transaction_id="txn_001",
        sku=SKU,
        quantity=2,
    )

    time.sleep(1.1)
    with pytest.raises(InventoryError) as exc:
        inventory.commit_hold(
            hold.hold_token
        )
    assert exc.value.code == "HOLD_EXPIRED"

def test_committed_hold_cannot_be_released():
    inventory = create_inventory(5)
    hold = inventory.create_hold(
        transaction_id="txn_001",
        sku=SKU,
        quantity=2,
    )

    inventory.commit_hold(
        hold.hold_token
    )

    with pytest.raises(InventoryError) as exc:
        inventory.release_hold(
            hold.hold_token
        )
    assert exc.value.code == "HOLD_ALREADY_COMMITTED"