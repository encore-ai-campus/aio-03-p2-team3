"""Explicit review and approval of packing totals, separate from core calculations."""
from copy import deepcopy
from decimal import Decimal
import re

from .packing import reconcile_packing as _reconcile_packing, _number, _plain
from .trade_documents import normalize_quantity_unit


def reconcile_packing(data):
    """Include input-normalization issues alongside core packing validation."""
    result = _reconcile_packing(data)
    for issue in data.get('_packing_input_issues', []):
        if issue not in result['issues']:
            result['issues'].append(issue)
    return result


PACKING_SOURCE_FIELDS = ("actual_package_count", "container_count", "declared_net_weight_kg",
                         "declared_gross_weight_kg", "declared_volume_cbm", "declared_total_quantity",
                         "declared_total_quantity_unit")
_AMOUNT = r"(\d+(?:,\d{3})*(?:\.\d+)?)"


def normalize_packing_inputs(data):
    """Parse explicit numeric annotations, retaining the original source values."""
    result = deepcopy(data)
    result.setdefault('_packing_original_totals', {field: data.get(field) for field in PACKING_SOURCE_FIELDS})
    result['_packing_input_issues'] = []
    suffixes = {
        'actual_package_count': r'(?:pallets?|plts?|packages?|pkgs?|cartons?|ctns?|boxes?)?',
        'declared_net_weight_kg': r'(?:kgs?|kilograms?)?',
        'declared_gross_weight_kg': r'(?:kgs?|kilograms?)?',
        'declared_volume_cbm': r'(?:cbm|m3|m³)?',
        'container_count': r"(?:[x×*]\s*\d+(?:\.\d+)?\s*(?:ft|feet|'))?\s*(?:containers?|컨테이너)?",
    }
    for field, suffix in suffixes.items():
        value = result.get(field)
        if value in (None, ''):
            continue
        match = re.fullmatch(r'\s*' + _AMOUNT + r'\s*' + suffix + r'\s*', str(value), re.I)
        if match and _number(match[1]) is not None:
            result[field] = _plain(_number(match[1]))
    quantity = result.get('declared_total_quantity')
    if quantity not in (None, ''):
        match = re.fullmatch(r'\s*' + _AMOUNT + r'\s*([A-Za-z]+)?\s*', str(quantity), re.I)
        if match and _number(match[1]) is not None:
            unit = normalize_quantity_unit(match[2])
            supplied_unit = normalize_quantity_unit(result.get('declared_total_quantity_unit'))
            if unit and supplied_unit and unit != supplied_unit:
                result['_packing_input_issues'].append('Source total quantity has conflicting units; correct its unit before approving totals')
            else:
                result['declared_total_quantity'] = _plain(_number(match[1]))
                if unit:
                    result['declared_total_quantity_unit'] = unit
    return result


def packing_total_changes(data, check=None):
    """Propose only totals supported by complete row calculations."""
    check = check or reconcile_packing(data)
    changes = []
    for key, field, label in (
        ('package_count', 'actual_package_count', 'Packages'),
        ('net_weight_kg', 'declared_net_weight_kg', 'NW (kg)'),
        ('gross_weight_kg', 'declared_gross_weight_kg', 'GW (kg)'),
        ('volume_cbm', 'declared_volume_cbm', 'CBM'),
    ):
        computed = check['calculated'][key]
        if computed is not None and _number(data.get(field)) != Decimal(computed):
            original = data.get('_packing_original_totals', {}).get(field, data.get(field))
            changes.append({'field': field, 'label': label, 'source': str(original) if original is not None else 'Not provided',
                            'calculated': computed})
    if check['quantity_complete']:
        quantities = check['quantities']
        unit = normalize_quantity_unit(data.get('declared_total_quantity_unit'))
        if unit not in quantities or _number(data.get('declared_total_quantity')) != Decimal(quantities[unit]):
            original = data.get('_packing_original_totals', {}).get('declared_total_quantity', data.get('declared_total_quantity'))
            source_text = str(original) if original is not None else 'Not provided'
            original_unit = data.get('_packing_original_totals', {}).get('declared_total_quantity_unit', unit)
            if _number(original) is not None and original_unit:
                source_text += ' ' + str(original_unit)
            changes.append({'field': 'declared_total_quantity', 'label': 'Quantity (by unit)',
                            'source': source_text,
                            'calculated': ' + '.join(f'{value} {key}' for key, value in quantities.items())})
    return changes


def apply_approved_packing_totals(data):
    """Apply row totals after explicit approval; never change item rows or infer containers."""
    result = normalize_packing_inputs(data)
    check = reconcile_packing(result)
    if check['issues'] or not check['quantity_complete']:
        raise ValueError('Correct invalid packing rows, units, and container counts before approving totals')
    for key, field in (('package_count', 'actual_package_count'), ('net_weight_kg', 'declared_net_weight_kg'),
                       ('gross_weight_kg', 'declared_gross_weight_kg'), ('volume_cbm', 'declared_volume_cbm')):
        if check['calculated'][key] is not None:
            result[field] = check['calculated'][key]
    quantities = check['quantities']
    unit = normalize_quantity_unit(result.get('declared_total_quantity_unit'))
    if unit not in quantities:
        unit = next(iter(quantities)) if len(quantities) == 1 else None
    result['declared_total_quantity'] = quantities.get(unit)
    result['declared_total_quantity_unit'] = unit
    result['_packing_approved_quantities'] = dict(quantities)
    result['_packing_totals_approved'] = True
    return result


