import config

def is_interesting(job):
    """
    Determines if a job is interesting based on criteria:
    - Material contains 'sheet' (tablă)
    - Price > 250 EUR
    """
    material = job.get('material', '').lower()
    price = job.get('price', 0.0)
    
    # Filter by price first (efficiency)
    try:
        price_val = float(price)
    except (ValueError, TypeError):
        price_val = 0.0

    if price_val < config.MIN_PRICE_VALUE:
        return False

    # Check material OR process
    process = job.get('process', '').lower()
    
    match_material = any(keyword in material for keyword in config.INTERESTING_MATERIAL_KEYWORDS)
    match_process = any(keyword in process for keyword in config.INTERESTING_MATERIAL_KEYWORDS)
    
    if not (match_material or match_process):
        return False
    
    # Optional: Negative filters (e.g. exclude certain processes if needed)
    # For now, we only need the positive ones as per requirement, 
    # but we could add:
    # if "3d print" in process.lower(): return False

    return True
