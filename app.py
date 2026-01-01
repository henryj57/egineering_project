#!/usr/bin/env python3
"""
AV Rack Documentation Generator - Web Interface
Upload a CSV and get a professional rack elevation PDF
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
    page_title="AV Rack Elevation Generator",
    page_icon="🗄️",
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
    
    # Database lookup
    if use_database and DATABASE_AVAILABLE:
        try:
            db = get_database()
            for product in filtered_products:
                model_num = product.part_number or product.model
                db_specs = db.get_rack_specs(model_num)
                
                if db_specs:
                    lookup_key = f"{product.brand} {product.model}".strip().lower()
                    specs_lookup[lookup_key] = db_specs
                else:
                    products_needing_ai.append(product)
        except Exception as e:
            products_needing_ai = list(filtered_products)
    else:
        products_needing_ai = list(filtered_products)
    
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


def main():
    # Header
    st.markdown('<p class="main-header">🗄️ AV Rack Elevation Generator</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Upload a client CSV and generate professional rack elevation PDFs</p>', unsafe_allow_html=True)
    
    # Sidebar settings
    with st.sidebar:
        st.header("⚙️ Settings")
        
        project_name = st.text_input("Project Name", value="AV System", help="Name of the project for the title block")
        company_name = st.text_input("Company Name", value="Your Company", help="Your company name for the title block")
        
        st.divider()
        
        page_size = st.selectbox(
            "Page Size",
            options=["tabloid", "arch_c", "arch_d", "letter"],
            format_func=lambda x: {
                "letter": "Letter (8.5×11)",
                "tabloid": "Tabloid (11×17) - Recommended",
                "arch_c": "ARCH C (18×24)",
                "arch_d": "ARCH D (24×36) - Print"
            }[x],
            index=0,
            help="Page size for the PDF. Tabloid works well on screen, ARCH D for client prints."
        )
        
        rack_size_override = st.number_input(
            "Rack Size (U)",
            min_value=8,
            max_value=52,
            value=42,
            help="Default rack size. Set to 0 to auto-detect from CSV."
        )
        
        st.divider()
        
        use_database = st.checkbox("Use MySQL Database", value=DATABASE_AVAILABLE, disabled=not DATABASE_AVAILABLE)
        use_ai = st.checkbox("Use AI (OpenAI)", value=True, help="Use OpenAI to look up product specs")
        
        if not DATABASE_AVAILABLE:
            st.caption("⚠️ MySQL not configured")
    
    # Main content area
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.header("📤 Upload CSV")
        
        uploaded_file = st.file_uploader(
            "Choose a CSV file",
            type=['csv'],
            help="Upload a client proposal CSV with equipment list"
        )
        
        if uploaded_file is not None:
            # Save uploaded file temporarily
            with tempfile.NamedTemporaryFile(delete=False, suffix='.csv', mode='wb') as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                tmp_csv_path = tmp_file.name
            
            try:
                # Detect racks from CSV
                rack_info = get_rack_info_from_csv(tmp_csv_path)
                
                st.markdown('<div class="info-box">', unsafe_allow_html=True)
                st.write(f"**📄 File:** {uploaded_file.name}")
                
                if rack_info['racks']:
                    st.write(f"**🗄️ Detected Racks:** {rack_info['total_racks']}")
                    for rack in rack_info['racks']:
                        st.write(f"  • {rack.model}: {rack.size_u}U ({rack.rack_type})")
                    detected_size = rack_info['default_size']
                else:
                    detected_size = rack_size_override
                    st.write("ℹ️ No rack enclosures detected in CSV")
                
                st.markdown('</div>', unsafe_allow_html=True)
                
                # Use detected size if available
                actual_rack_size = detected_size if rack_size_override == 42 else rack_size_override
                
                # Generate button
                if st.button("🚀 Generate Rack Elevation", type="primary", use_container_width=True):
                    with st.spinner("Processing..."):
                        # Progress container
                        progress_container = st.empty()
                        
                        def update_progress(msg):
                            progress_container.info(msg)
                        
                        # Parse CSV
                        update_progress("📄 Parsing CSV...")
                        products = parse_client_csv(tmp_csv_path)
                        products = get_unique_products_with_quantities(products)
                        
                        if not products:
                            st.error("❌ No products found in CSV")
                            return
                        
                        update_progress(f"📦 Found {len(products)} unique products")
                        
                        # Enrich with specs
                        rack_items = enrich_products_with_specs_streamlit(
                            products,
                            use_database=use_database,
                            use_ai=use_ai,
                            progress_callback=update_progress
                        )
                        
                        # Expand quantities
                        rack_items = expand_quantities(rack_items)
                        
                        if not rack_items:
                            st.error("❌ No rack-mountable items found")
                            return
                        
                        update_progress(f"🗄️ {len(rack_items)} items to rack")
                        
                        # Calculate total U needed
                        total_u = sum(item.rack_units for item in rack_items)
                        
                        # Check if we need to split
                        layouts = []
                        if total_u > (actual_rack_size - 3):
                            av_items, network_items = split_into_av_and_network(rack_items)
                            
                            av_u = sum(item.rack_units for item in av_items)
                            av_rack_size = 48 if av_u + len(av_items)//2 > (actual_rack_size - 4) else actual_rack_size
                            
                            if av_items:
                                av_layout = arrange_rack(av_items, rack_size_u=av_rack_size)
                                av_layout.project_name = f"{project_name} - AV Rack ({av_rack_size}U)"
                                layouts.append(("AV Rack", av_layout))
                            
                            if network_items:
                                net_layout = arrange_rack(network_items, rack_size_u=actual_rack_size)
                                net_layout.project_name = f"{project_name} - Network Rack ({actual_rack_size}U)"
                                layouts.append(("Network Rack", net_layout))
                        else:
                            layout = arrange_rack(rack_items, rack_size_u=actual_rack_size)
                            layout.project_name = project_name
                            layouts.append(("Main Rack", layout))
                        
                        # Generate PDF
                        update_progress("📑 Generating PDF...")
                        
                        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_pdf:
                            tmp_pdf_path = tmp_pdf.name
                        
                        all_layouts = [l[1] for l in layouts]
                        generate_rack_pdf(
                            layout=all_layouts if len(all_layouts) > 1 else all_layouts[0],
                            output_path=tmp_pdf_path,
                            project_name=project_name,
                            company_name=company_name,
                            revision="A",
                            page_size=page_size
                        )
                        
                        # Store results in session state
                        st.session_state['pdf_path'] = tmp_pdf_path
                        st.session_state['layouts'] = layouts
                        st.session_state['project_name'] = project_name
                        
                        progress_container.empty()
                        st.success(f"✅ Generated {len(layouts)} page(s)!")
                        st.rerun()
            
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
                import traceback
                st.code(traceback.format_exc())
            
            finally:
                # Clean up temp CSV
                if os.path.exists(tmp_csv_path):
                    os.unlink(tmp_csv_path)
    
    with col2:
        st.header("📄 Preview & Download")
        
        if 'pdf_path' in st.session_state and os.path.exists(st.session_state['pdf_path']):
            # Show rack layout previews
            for name, layout in st.session_state.get('layouts', []):
                with st.expander(f"🗄️ {name} ({layout.rack_size_u}U)", expanded=True):
                    preview_text = generate_rack_preview_text(layout)
                    st.markdown(f'<div class="rack-preview">{preview_text}</div>', unsafe_allow_html=True)
                    
                    # Stats
                    col_a, col_b, col_c = st.columns(3)
                    col_a.metric("Equipment", f"{layout.total_equipment_u}U")
                    col_b.metric("Weight", f"{layout.total_weight:.0f} lbs")
                    col_c.metric("BTU", f"{layout.total_btu:.0f}")
            
            st.divider()
            
            # Download button
            with open(st.session_state['pdf_path'], 'rb') as pdf_file:
                pdf_bytes = pdf_file.read()
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = st.session_state.get('project_name', 'Rack').replace(' ', '_')
            filename = f"Rack_Elevation_{safe_name}_{timestamp}.pdf"
            
            st.download_button(
                label="⬇️ Download PDF",
                data=pdf_bytes,
                file_name=filename,
                mime="application/pdf",
                type="primary",
                use_container_width=True
            )
            
            # Show PDF preview (embedded)
            st.divider()
            st.subheader("PDF Preview")
            
            # Encode PDF for display
            base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
            pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="600" type="application/pdf"></iframe>'
            st.markdown(pdf_display, unsafe_allow_html=True)
        
        else:
            st.info("👆 Upload a CSV and click 'Generate' to see the rack elevation preview")
            
            # Show example
            with st.expander("📋 Example CSV Format"):
                st.code("""Quantity,Part Number,Cost Price,Sell Price,Phase,LocationPath,System
1,USW-PRO-24-POE,1200,1500,Finish,Equipment Closet,Network & WiFi
1,UDM-PRO-MAX,600,750,Finish,Equipment Closet,Network & WiFi
1,PAV-SIPA125SM-10,2310,3000,Finish,Equipment Closet,Audio
1,SSC-0012,321,450,Finish,Equipment Closet,Automation
1,HQP7-2,913,1200,Finish,Equipment Closet,Lighting Control
""", language="csv")


if __name__ == "__main__":
    main()

