#!/usr/bin/env python3
"""
AV Documentation Generator - Web Interface
Upload a CSV and get professional rack elevations and block diagrams
"""

import streamlit as st
import tempfile
import os
from pathlib import Path
from datetime import datetime
import base64

# Import our modules
from csv_parser import parse_client_csv, get_unique_products_with_quantities, get_rack_info_from_csv
from rack_arranger import arrange_rack, expand_quantities, print_rack_layout
from pdf_generator import generate_rack_pdf

# Try to import database client
try:
    from db_client import get_database, MYSQL_AVAILABLE
    DATABASE_AVAILABLE = MYSQL_AVAILABLE
except (ImportError, ValueError, PermissionError, OSError):
    DATABASE_AVAILABLE = False
    def get_database():
        return None

# Page configuration
st.set_page_config(
    page_title="AV Documentation Generator",
    page_icon="📐",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1E3A5F;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #666;
        margin-bottom: 2rem;
    }
    .stButton > button {
        background-color: #1E3A5F;
        color: white;
        font-weight: 600;
        padding: 0.5rem 2rem;
        border-radius: 8px;
    }
    .stButton > button:hover {
        background-color: #2E5A8F;
    }
    .success-box {
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        border-radius: 8px;
        padding: 1rem;
        margin: 1rem 0;
    }
    .info-box {
        background-color: #e7f3ff;
        border: 1px solid #b6d4fe;
        border-radius: 8px;
        padding: 1rem;
        margin: 1rem 0;
    }
    .rack-preview {
        background-color: #f8f9fa;
        border: 2px solid #dee2e6;
        border-radius: 8px;
        padding: 1rem;
        font-family: monospace;
        font-size: 0.8rem;
        max-height: 400px;
        overflow-y: auto;
    }
    .section-header {
        font-size: 1rem;
        font-weight: 600;
        color: #1E3A5F;
        margin: 1rem 0 0.5rem 0;
        padding-bottom: 0.3rem;
        border-bottom: 2px solid #E67E22;
    }
</style>
""", unsafe_allow_html=True)


def split_into_av_and_network(rack_items):
    """Split rack items into AV and Network categories"""
    av_items = []
    network_items = []
    
    network_brands = ['ubiquiti', 'pakedge', 'araknis', 'cisco', 'netgear', 'access networks']
    network_models = ['usw-', 'udm-', 'uap-', 'an-', 'ss42', 'switch', 'router', 'gateway']
    
    for item in rack_items:
        subsystem = getattr(item, 'subsystem', None) or ''
        subsystem_lower = subsystem.lower() if subsystem else ''
        
        if 'network' in subsystem_lower or 'net' in subsystem_lower:
            network_items.append(item)
            continue
        elif 'av' in subsystem_lower or 'audio' in subsystem_lower or 'video' in subsystem_lower:
            av_items.append(item)
            continue
        
        brand_lower = item.brand.lower() if item.brand else ""
        model_lower = item.model.lower() if item.model else ""
        name_lower = item.name.lower() if item.name else ""
        
        is_network = (
            any(nb in brand_lower for nb in network_brands) or
            any(nm in model_lower for nm in network_models) or
            any(nm in name_lower for nm in network_models)
        )
        
        if is_network:
            network_items.append(item)
        else:
            av_items.append(item)
    
    return av_items, network_items


def enrich_products_with_specs_streamlit(products, use_database=True, use_ai=True, progress_callback=None):
    """Get product specifications - Streamlit version with progress updates"""
    from rack_arranger import RackItem, RackItemType
    import math
    
    rack_items = []
    specs_lookup = {}
    products_needing_ai = []
    
    # Pre-filter
    def is_clearly_not_rack_mountable(product):
        if not product.model and not product.part_number:
            return True
        name = (product.name or '').lower()
        category = (product.category or '').lower()
        brand = (product.brand or '').lower()
        
        network_brands = ['araknis', 'ubiquiti', 'cisco', 'netgear', 'pakedge', 'access networks', 'motu']
        if any(nb in brand for nb in network_brands):
            return False
        if 'networking' in category or 'switches' in category:
            return False
        
        skip_keywords = [
            'pre-wire', 'prewire', 'cable', 'wire ', 'in-wall', 'in-ceiling',
            'outdoor speaker', 'screen', 'projector mount', 'tv mount',
            'wallplate', 'wall plate', 'keypad', 'dimmer', 'sensor',
            'back box', 'backbox', 'allowance', 'labor', 'installation',
        ]
        combined_text = f"{name} {category}"
        return any(kw in combined_text for kw in skip_keywords)
    
    filtered_products = [p for p in products if not is_clearly_not_rack_mountable(p)]
    
    if progress_callback:
        progress_callback(f"📦 {len(filtered_products)} products after filtering")
    
    # ========== STEP 1: D-Tools racks.db lookup (fastest, most accurate) ==========
    products_not_in_dtools = []
    try:
        from import_dtools_products import get_equipment_specs
        dtools_found = 0
        for product in filtered_products:
            model_num = product.part_number or product.model
            dtools_specs = get_equipment_specs(model=model_num, part_number=product.part_number)
            
            if dtools_specs and dtools_specs.get('rack_units', 0) > 0:
                lookup_key = f"{product.brand} {product.model}".strip().lower()
                specs_lookup[lookup_key] = {
                    'rack_units': dtools_specs['rack_units'],
                    'weight': dtools_specs.get('weight', 5.0),
                    'btu': dtools_specs.get('btu', 0),
                    'depth': dtools_specs.get('depth', 0),
                    'is_rack_mountable': dtools_specs.get('rack_mounted', True),
                }
                dtools_found += 1
            else:
                products_not_in_dtools.append(product)
        
        if progress_callback:
            progress_callback(f"📚 Found {dtools_found} in D-Tools catalog")
    except ImportError:
        products_not_in_dtools = list(filtered_products)
    except Exception as e:
        if progress_callback:
            progress_callback(f"⚠️ D-Tools lookup error: {e}")
        products_not_in_dtools = list(filtered_products)
    
    # ========== STEP 2: MySQL database lookup (fallback) ==========
    if use_database and DATABASE_AVAILABLE and products_not_in_dtools:
        try:
            db = get_database()
            for product in products_not_in_dtools:
                model_num = product.part_number or product.model
                db_specs = db.get_rack_specs(model_num)
                
                if db_specs:
                    lookup_key = f"{product.brand} {product.model}".strip().lower()
                    specs_lookup[lookup_key] = db_specs
                else:
                    products_needing_ai.append(product)
        except Exception as e:
            products_needing_ai = list(products_not_in_dtools)
    else:
        products_needing_ai = list(products_not_in_dtools)
    
    # OpenAI lookup
    if use_ai and products_needing_ai:
        try:
            from openai_client import get_openai_client
            ai_client = get_openai_client()
            
            product_dicts = [
                {"brand": p.brand, "model": p.model, "category": p.category, "name": p.name}
                for p in products_needing_ai
            ]
            
            if progress_callback:
                progress_callback(f"🤖 Analyzing {len(products_needing_ai)} products with AI...")
            
            ai_specs = ai_client.get_product_specs(product_dicts)
            
            for key, value in ai_specs.items():
                if key not in specs_lookup:
                    specs_lookup[key] = value
        except Exception as e:
            if progress_callback:
                progress_callback(f"⚠️ AI lookup failed: {e}")
    
    # Build rack items
    for product in filtered_products:
        lookup_key = f"{product.brand} {product.model}".strip().lower()
        specs = specs_lookup.get(lookup_key, {})
        
        if specs:
            if not specs.get('is_rack_mountable', True):
                continue
            
            rack_units = math.ceil(specs.get('rack_units', 0)) if specs.get('rack_units', 0) > 0 else 0
            if rack_units == 0:
                continue
            
            rack_item = RackItem(
                item_type=RackItemType.EQUIPMENT,
                name=product.name,
                brand=product.brand,
                model=product.model,
                rack_units=int(rack_units),
                weight=specs.get('weight', 10.0),
                btu=specs.get('btu', 0) or product.calculated_btu or 0,
                connections=specs.get('connections'),
                quantity=product.quantity,
                subsystem=specs.get('subsystem', '')
            )
            rack_items.append(rack_item)
    
    return rack_items


def generate_rack_preview_text(layout):
    """Generate text preview of rack layout"""
    lines = []
    lines.append(f"{'='*60}")
    lines.append(f"RACK LAYOUT - {layout.rack_size_u}U Rack")
    lines.append(f"{'='*60}")
    lines.append(f"Equipment: {layout.total_equipment_u}U | Vents/Blanks: {layout.total_vent_u}U | Free: {layout.remaining_u}U")
    lines.append(f"Total Weight: {layout.total_weight:.1f} lbs | Total BTU: {layout.total_btu:.0f}")
    lines.append(f"{'='*60}")
    lines.append("")
    
    for item in reversed(layout.items):
        if item.rack_units > 1:
            pos_str = f"U{item.position_u}-{item.position_u + item.rack_units - 1}"
        else:
            pos_str = f"U{item.position_u}"
        
        icon = "📦" if item.is_equipment else "🌬️"
        name = f"{item.brand} {item.model}".strip() if item.is_equipment else item.display_name
        
        weight_str = f"{item.weight:.1f}lb" if item.weight else ""
        btu_str = f"{item.btu:.0f}BTU" if item.btu else ""
        
        line = f"  {pos_str:10} │ {icon} {name:40} │ {weight_str:8} {btu_str}"
        lines.append(line)
    
    lines.append("")
    lines.append(f"{'='*60}")
    
    return "\n".join(lines)


def detect_system_defaults(csv_path):
    """Auto-detect system settings from equipment in CSV"""
    defaults = {
        'video': 'Centralized',
        'audio': 'Centralized',
        'network': 'All Networked',
        'control': 'Savant',
        'rack_location': 'Equipment Closet'
    }
    
    try:
        with open(csv_path, 'r', encoding='latin-1') as f:
            content = f.read().lower()
            
            # Detect control system
            if 'savant' in content or 'ssc-' in content or 'pkg-mac' in content:
                defaults['control'] = 'Savant'
            elif 'control4' in content or 'c4-' in content:
                defaults['control'] = 'Control4'
            elif 'crestron' in content or 'cp4' in content:
                defaults['control'] = 'Crestron'
            
            # Detect video distribution
            if 'ps65' in content or 'ps80' in content or 'ub32' in content:
                defaults['video'] = 'Centralized (IP Video)'
            elif 'hdmi matrix' in content or 'hdbt' in content:
                defaults['video'] = 'Centralized (Matrix)'
            
            # Detect audio
            if 'pav-sipa' in content or 'savant amp' in content:
                defaults['audio'] = 'Centralized'
            elif 'sonos' in content:
                defaults['audio'] = 'Distributed (Sonos)'
            
            # Try to detect rack location
            if 'equipment closet' in content:
                defaults['rack_location'] = 'Equipment Closet'
            elif 'mdf' in content:
                defaults['rack_location'] = 'MDF'
            elif 'basement' in content:
                defaults['rack_location'] = 'Basement Equipment Room'
                
    except Exception:
        pass
    
    return defaults


def main():
    # Header
    st.markdown('<p class="main-header">📐 AV Documentation Generator</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Upload a CSV to generate professional rack elevations and system block diagrams</p>', unsafe_allow_html=True)
    
    # Sidebar settings
    with st.sidebar:
        st.header("⚙️ Project Settings")
        
        project_name = st.text_input("Project Name", value="AV System", help="Name of the project")
        company_name = st.text_input("Company Name", value="Your Company", help="Your company name")
        
        st.divider()
        
        # Output options
        st.markdown('<p class="section-header">📄 Output Options</p>', unsafe_allow_html=True)
        
        generate_rack = st.checkbox("🗄️ Rack Elevation", value=True, help="Generate rack elevation diagram")
        generate_block = st.checkbox("📊 Block Diagram", value=True, help="Generate system block diagram")
        
        page_size = st.selectbox(
            "Page Size",
            options=["tabloid", "arch_c", "arch_d", "letter"],
            format_func=lambda x: {
                "letter": "Letter (8.5×11)",
                "tabloid": "Tabloid (11×17)",
                "arch_c": "ARCH C (18×24)",
                "arch_d": "ARCH D (24×36)"
            }[x],
            index=0
        )
        
        st.divider()
        
        # Data sources
        st.markdown('<p class="section-header">🔌 Data Sources</p>', unsafe_allow_html=True)
        
        # Check if D-Tools racks.db exists
        import os
        dtools_available = os.path.exists(os.path.join(os.path.dirname(__file__), "racks.db"))
        
        st.checkbox("📚 D-Tools Catalog", value=dtools_available, disabled=True, 
                   help="racks.db - Primary source for accurate specs")
        if dtools_available:
            st.caption("✅ D-Tools catalog loaded (racks.db)")
        else:
            st.caption("⚠️ Run import_dtools_products.py to load catalog")
        
        use_database = st.checkbox("🗄️ MySQL Database", value=DATABASE_AVAILABLE, disabled=not DATABASE_AVAILABLE,
                                  help="Fallback if not in D-Tools")
        use_ai = st.checkbox("🤖 OpenAI (AI Lookup)", value=True,
                            help="Last resort for unknown products")
        
        if not DATABASE_AVAILABLE:
            st.caption("⚠️ MySQL not configured")
    
    # Main content area - 3 columns
    col1, col2, col3 = st.columns([1, 1, 1])
    
    with col1:
        st.header("📤 Upload CSV")
        
        uploaded_file = st.file_uploader(
            "Choose a CSV file",
            type=['csv'],
            help="Upload a client proposal CSV with equipment list"
        )
        
        # Store CSV path in session for other functions
        tmp_csv_path = None
        
        if uploaded_file is not None:
            # Save uploaded file temporarily
            with tempfile.NamedTemporaryFile(delete=False, suffix='.csv', mode='wb') as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                tmp_csv_path = tmp_file.name
                st.session_state['tmp_csv_path'] = tmp_csv_path
            
            try:
                # Detect racks from CSV
                rack_info = get_rack_info_from_csv(tmp_csv_path)
                
                st.markdown('<div class="info-box">', unsafe_allow_html=True)
                st.write(f"**📄 File:** {uploaded_file.name}")
                
                if rack_info['racks']:
                    st.write(f"**🗄️ Detected Racks:** {rack_info['total_racks']}")
                    for rack in rack_info['racks']:
                        st.write(f"  • {rack.model}: {rack.size_u}U")
                    detected_size = rack_info['default_size']
                else:
                    detected_size = 42
                    st.write("ℹ️ No rack enclosures detected")
                
                st.session_state['detected_rack_size'] = detected_size
                st.markdown('</div>', unsafe_allow_html=True)
                
                # Auto-detect system settings
                defaults = detect_system_defaults(tmp_csv_path)
                st.session_state['system_defaults'] = defaults
                
            except Exception as e:
                st.error(f"❌ Error reading CSV: {str(e)}")
    
    with col2:
        st.header("🎛️ System Configuration")
        
        if uploaded_file is not None:
            defaults = st.session_state.get('system_defaults', {})
            
            # Rack settings
            st.markdown('<p class="section-header">🗄️ Rack Settings</p>', unsafe_allow_html=True)
            
            detected_size = st.session_state.get('detected_rack_size', 42)
            rack_size = st.number_input(
                "Rack Size (U)",
                min_value=8,
                max_value=52,
                value=detected_size,
                help="Rack unit height"
            )
            
            rack_location = st.text_input(
                "Rack Location Name",
                value=defaults.get('rack_location', 'Equipment Closet'),
                help="Name for the head-end location"
            )
            
            # System Intent Questions
            st.markdown('<p class="section-header">📊 System Architecture</p>', unsafe_allow_html=True)
            
            video_dist = st.selectbox(
                "Video Distribution",
                options=["Centralized (IP Video)", "Centralized (Matrix)", "Distributed", "Hybrid", "None"],
                index=0 if 'Centralized' in defaults.get('video', '') else 2,
                help="How video is distributed throughout the home"
            )
            
            audio_arch = st.selectbox(
                "Audio Architecture", 
                options=["Centralized", "Distributed (Sonos)", "Distributed (HEOS)", "Hybrid", "None"],
                index=0 if 'Centralized' in defaults.get('audio', '') else 1,
                help="How audio is distributed"
            )
            
            network_arch = st.selectbox(
                "Network Architecture",
                options=["All Networked", "Partial", "Standalone"],
                index=0,
                help="Network connectivity approach"
            )
            
            control_system = st.selectbox(
                "Control System",
                options=["Savant", "Control4", "Crestron", "RTI", "URC", "Other", "None"],
                index=["Savant", "Control4", "Crestron", "RTI", "URC", "Other", "None"].index(defaults.get('control', 'Savant')),
                help="Primary automation/control system"
            )
            
            # Store in session state
            st.session_state['system_config'] = {
                'rack_size': rack_size,
                'rack_location': rack_location,
                'video': video_dist.split(' ')[0],  # Just "Centralized", "Distributed", etc.
                'audio': audio_arch.split(' ')[0],
                'network': network_arch,
                'control': control_system
            }
            
            st.divider()
            
            # Generate button
            if st.button("🚀 Generate Documents", type="primary", use_container_width=True):
                if not generate_rack and not generate_block:
                    st.warning("Please select at least one output type")
                else:
                    generate_documents(
                        tmp_csv_path, 
                        project_name, 
                        company_name,
                        st.session_state['system_config'],
                        generate_rack,
                        generate_block,
                        use_database,
                        use_ai,
                        page_size
                    )
        else:
            st.info("👈 Upload a CSV file to configure system settings")
            
            with st.expander("📋 Example CSV Format"):
                st.code("""Quantity,Part Number,Cost Price,Sell Price,Phase,LocationPath,System
1,USW-PRO-24-POE,1200,1500,Finish,Equipment Closet,Network & WiFi
1,UDM-PRO-MAX,600,750,Finish,Equipment Closet,Network & WiFi
1,PAV-SIPA125SM-10,2310,3000,Finish,Equipment Closet,Audio
1,QN65QN90FAFXZA,1200,1800,Finish,1st Level: Living Room,Video
1,PS65,700,1000,Finish,1st Level: Living Room,Video
""", language="csv")
    
    with col3:
        st.header("📄 Preview & Download")
        
        # Check for generated files
        if 'generated_files' in st.session_state:
            files = st.session_state['generated_files']
            
            for file_info in files:
                with st.expander(f"📄 {file_info['name']}", expanded=True):
                    if file_info['type'] == 'rack':
                        # Show rack preview
                        for name, layout in file_info.get('layouts', []):
                            st.write(f"**{name}** ({layout.rack_size_u}U)")
                            col_a, col_b, col_c = st.columns(3)
                            col_a.metric("Equipment", f"{layout.total_equipment_u}U")
                            col_b.metric("Weight", f"{layout.total_weight:.0f} lbs")
                            col_c.metric("BTU", f"{layout.total_btu:.0f}")
                    elif file_info['type'] == 'block':
                        st.write("System block diagram showing equipment distribution")
            
            st.divider()
            
            # Combined download or separate downloads
            if len(files) == 1:
                file_info = files[0]
                with open(file_info['path'], 'rb') as f:
                    pdf_bytes = f.read()
                
                st.download_button(
                    label=f"⬇️ Download {file_info['name']}",
                    data=pdf_bytes,
                    file_name=file_info['filename'],
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True
                )
            else:
                # Multiple files - offer separate downloads
                for file_info in files:
                    with open(file_info['path'], 'rb') as f:
                        pdf_bytes = f.read()
                    
                    st.download_button(
                        label=f"⬇️ {file_info['name']}",
                        data=pdf_bytes,
                        file_name=file_info['filename'],
                        mime="application/pdf",
                        use_container_width=True,
                        key=f"download_{file_info['name']}"
                    )
            
            # Show PDF preview
            st.divider()
            st.subheader("PDF Preview")
            
            # Show first file preview
            if files:
                with open(files[0]['path'], 'rb') as f:
                    pdf_bytes = f.read()
                base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
                pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="500" type="application/pdf"></iframe>'
                st.markdown(pdf_display, unsafe_allow_html=True)
        else:
            st.info("👈 Configure settings and click 'Generate' to create documents")


def generate_documents(csv_path, project_name, company_name, config, 
                       generate_rack, generate_block, use_database, use_ai, page_size):
    """Generate all requested documents"""
    
    generated_files = []
    progress = st.progress(0, text="Starting...")
    
    try:
        # Parse CSV
        progress.progress(10, text="📄 Parsing CSV...")
        products = parse_client_csv(csv_path)
        products = get_unique_products_with_quantities(products)
        
        if not products:
            st.error("❌ No products found in CSV")
            return
        
        # Generate Rack Elevation
        if generate_rack:
            progress.progress(30, text="🗄️ Processing rack items...")
            
            rack_items = enrich_products_with_specs_streamlit(
                products,
                use_database=use_database,
                use_ai=use_ai
            )
            
            rack_items = expand_quantities(rack_items)
            
            if rack_items:
                total_u = sum(item.rack_units for item in rack_items)
                rack_size = config['rack_size']
                
                layouts = []
                if total_u > (rack_size - 3):
                    av_items, network_items = split_into_av_and_network(rack_items)
                    
                    av_u = sum(item.rack_units for item in av_items)
                    av_rack_size = 48 if av_u + len(av_items)//2 > (rack_size - 4) else rack_size
                    
                    if av_items:
                        av_layout = arrange_rack(av_items, rack_size_u=av_rack_size)
                        av_layout.project_name = f"{project_name} - AV Rack"
                        layouts.append(("AV Rack", av_layout))
                    
                    if network_items:
                        net_layout = arrange_rack(network_items, rack_size_u=rack_size)
                        net_layout.project_name = f"{project_name} - Network Rack"
                        layouts.append(("Network Rack", net_layout))
                else:
                    layout = arrange_rack(rack_items, rack_size_u=rack_size)
                    layout.project_name = project_name
                    layouts.append(("Main Rack", layout))
                
                # Generate PDF
                progress.progress(50, text="📑 Generating rack PDF...")
                
                with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_pdf:
                    rack_pdf_path = tmp_pdf.name
                
                all_layouts = [l[1] for l in layouts]
                generate_rack_pdf(
                    layout=all_layouts if len(all_layouts) > 1 else all_layouts[0],
                    output_path=rack_pdf_path,
                    project_name=project_name,
                    company_name=company_name,
                    revision="A",
                    page_size=page_size
                )
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                generated_files.append({
                    'name': 'Rack Elevation',
                    'type': 'rack',
                    'path': rack_pdf_path,
                    'filename': f"Rack_Elevation_{project_name.replace(' ', '_')}_{timestamp}.pdf",
                    'layouts': layouts
                })
        
        # Generate Block Diagram
        if generate_block:
            progress.progress(70, text="📊 Generating block diagram...")
            
            try:
                from block_diagram import generate_block_diagram, SystemIntent
                
                # Create intent from config
                intent = SystemIntent(
                    video_distribution=config['video'],
                    audio_architecture=config['audio'],
                    network_architecture=config['network'],
                    control_system=config['control'],
                    rack_location=config['rack_location']
                )
                
                with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_pdf:
                    block_pdf_path = tmp_pdf.name
                
                generate_block_diagram(
                    equipment_csv=csv_path,
                    output_path=block_pdf_path,
                    project_name=project_name,
                    intent=intent,
                    page_size=page_size
                )
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                generated_files.append({
                    'name': 'Block Diagram',
                    'type': 'block',
                    'path': block_pdf_path,
                    'filename': f"Block_Diagram_{project_name.replace(' ', '_')}_{timestamp}.pdf"
                })
                
            except Exception as e:
                st.warning(f"⚠️ Block diagram generation failed: {e}")
                import traceback
                st.code(traceback.format_exc())
        
        progress.progress(100, text="✅ Done!")
        
        # Store results
        st.session_state['generated_files'] = generated_files
        
        if generated_files:
            st.success(f"✅ Generated {len(generated_files)} document(s)!")
            st.rerun()
        else:
            st.warning("No documents were generated")
            
    except Exception as e:
        st.error(f"❌ Error: {str(e)}")
        import traceback
        st.code(traceback.format_exc())
    finally:
        progress.empty()


if __name__ == "__main__":
    main()
