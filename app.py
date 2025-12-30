import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os

# --- KONFİGÜRASYON ---
DB_NAME = "ilan_takip_v11_cognitive.db"  # V11 Botunun oluşturduğu DB
PAGE_TITLE = "ProSearcher V11 | Cognitive Radar"
PAGE_ICON = "🧠"

# --- STİL VE CSS (GÖRSEL PSİKOLOJİ) ---
# Kart Tasarımı: Sol kenarlık rengi karara göre değişir.
# Karanlık mod uyumlu, minimalist ve odaklı.
st.set_page_config(page_title=PAGE_TITLE, page_icon=PAGE_ICON, layout="wide")

st.markdown("""
    <style>
    /* Genel Ayarlar */
    .block-container {padding-top: 1rem; padding-bottom: 5rem;}
    
    /* Kart Tasarımı */
    .metric-card {
        background-color: #1E1E1E;
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 15px;
        border: 1px solid #333;
        transition: transform 0.2s;
    }
    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 10px rgba(0,0,0,0.3);
    }
    
    /* Karar Renkleri (Sol Kenarlık) */
    .border-gem { border-left: 5px solid #00b4d8 !important; } /* Turkuaz */
    .border-good { border-left: 5px solid #2a9d8f !important; } /* Yeşil */
    .border-spec { border-left: 5px solid #e9c46a !important; } /* Turuncu */
    .border-toxic { border-left: 5px solid #e63946 !important; } /* Kırmızı */
    
    /* Tipografi */
    .decision-label { font-weight: bold; font-size: 0.9rem; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 5px; }
    .price-main { font-size: 1.4rem; font-weight: 700; color: #ffffff; }
    .price-old { font-size: 0.9rem; text-decoration: line-through; color: #888; margin-left: 10px; }
    .ai-reason { font-style: italic; color: #aaa; font-size: 0.9rem; margin-top: 8px; border-left: 2px solid #444; padding-left: 10px; }
    
    /* Etiket Renkleri Metin */
    .text-gem { color: #00b4d8; }
    .text-good { color: #2a9d8f; }
    .text-spec { color: #e9c46a; }
    
    /* Gizli Link */
    .ad-link { text-decoration: none; color: inherit; }
    .ad-link:hover { text-decoration: none; color: inherit; }
    </style>
""", unsafe_allow_html=True)

# --- VERİ KATMANI ---
@st.cache_data(ttl=60) # 1 dakikada bir cache temizle (Canlıya yakın)
def load_data():
    if not os.path.exists(DB_NAME):
        return pd.DataFrame()
    
    conn = sqlite3.connect(DB_NAME)
    # V11 Şemasına uygun sorgu
    query = """
        SELECT 
            ilan_id, baslik, category, brand, tier, cluster_key,
            fiyat, para_birimi, fiyat_norm,
            first_seen, last_seen, initial_price,
            hourly_velocity, opportunity_score, risk_flags, decision_label,
            ilan_url
        FROM ilan
        WHERE aktif_mi = 1
    """
    try:
        df = pd.read_sql(query, conn)
        
        # Tarih dönüşümleri
        df['first_seen'] = pd.to_datetime(df['first_seen'])
        df['last_seen'] = pd.to_datetime(df['last_seen'])
        
        # Tier bilgisi bazen JSON içinde olabilir, V11 DB yapısına göre adjust etmek gerekebilir.
        # Şimdilik varsayılan kolonlardan okuyoruz.
        
        return df
    except Exception as e:
        st.error(f"Veritabanı okuma hatası: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

# --- MOCK DATA GENERATOR (Eğer DB boşsa UI'yi görmek için) ---
def generate_mock_data():
    data = [
        # Hidden Gem
        {"ilan_id": "1", "baslik": "Asus ROG Strix RTX 3080 White Edition", "category": "Ekran Kartı", "brand": "Asus", "fiyat": 12500, "para_birimi": "TL", "fiyat_norm": 12500, "opportunity_score": 92, "decision_label": "💎 HIDDEN GEM", "risk_flags": "[]", "hourly_velocity": 0.02, "ilan_url": "#"},
        # Good Deal
        {"ilan_id": "2", "baslik": "Logitech G Pro X Superlight", "category": "Mouse", "brand": "Logitech", "fiyat": 2200, "para_birimi": "TL", "fiyat_norm": 2200, "opportunity_score": 78, "decision_label": "✅ GOOD DEAL", "risk_flags": "[]", "hourly_velocity": 0.005, "ilan_url": "#"},
        # Speculative (Riskli Fırsat)
        {"ilan_id": "3", "baslik": "MSI 27 inç 165Hz Monitor (Ölü piksel var)", "category": "Monitor", "brand": "Msi", "fiyat": 3000, "para_birimi": "TL", "fiyat_norm": 3000, "opportunity_score": 85, "decision_label": "🎲 SPECULATIVE", "risk_flags": "['SUSPICIOUS_LOW_PRICE']", "hourly_velocity": 0.15, "ilan_url": "#"},
    ]
    return pd.DataFrame(data)

# --- UI BİLEŞENLERİ ---

def render_pulse_metrics(df):
    """Katman 1: Piyasa Nabzı (Pulse Screen)"""
    if df.empty: return
    
    col1, col2, col3, col4 = st.columns(4)
    
    gem_count = len(df[df['decision_label'] == '💎 HIDDEN GEM'])
    deal_count = len(df[df['decision_label'] == '✅ GOOD DEAL'])
    spec_count = len(df[df['decision_label'] == '🎲 SPECULATIVE'])
    
    # Piyasa Ateşi (Son 24 saatteki ortalama velocity)
    avg_velocity = df['hourly_velocity'].mean() * 100 # Yüzdeye çevir
    market_mood = "Sakin"
    if avg_velocity > 1.0: market_mood = "🔥 Yanıyor"
    elif avg_velocity > 0.5: market_mood = "🌊 Hareketli"
    
    col1.metric("💎 Gizli Cevherler", gem_count, help="Kaçırılmayacak fırsatlar")
    col2.metric("✅ İyi Fiyatlar", deal_count, help="Makul alım fırsatları")
    col3.metric("🎲 Spekülatif", spec_count, help="Yüksek risk / Yüksek ödül")
    col4.metric("🌡️ Piyasa Ateşi", market_mood, f"{avg_velocity:.2f}% / saat")

def render_opportunity_card(row):
    """Katman 2 & 3: Akıllı İlan Kartı"""
    
    # CSS Sınıfı Belirleme
    label = row['decision_label']
    border_class = "border-good"
    text_class = "text-good"
    if "HIDDEN GEM" in label:
        border_class = "border-gem"
        text_class = "text-gem"
    elif "SPECULATIVE" in label:
        border_class = "border-spec"
        text_class = "text-spec"
    
    # AI Yorumu Oluşturma (Eğer DB'de yoksa simüle et)
    # V11'de bu 'explanation' kolonunda geliyor.
    ai_reason = f"Fiyat piyasa medyanının altında."
    if row['opportunity_score'] > 90: ai_reason = "Fiyat mükemmel ve marka güvenilirliği en üst seviyede."
    elif "SPECULATIVE" in label: ai_reason = "Fiyat çok düşük ancak risk bayrakları var (Volatilite/Risk)."
    
    # HTML Kart
    card_html = f"""
    <div class="metric-card {border_class}">
        <div class="decision-label {text_class}">{label} <span style="font-size:0.7em; color:#666; float:right;">SKOR: {row['opportunity_score']}</span></div>
        <div style="font-size: 1.1rem; font-weight: 600; margin-bottom: 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
            <a href="{row['ilan_url']}" target="_blank" class="ad-link">{row['baslik']}</a>
        </div>
        <div>
            <span class="price-main">{row['fiyat']:,.0f} {row['para_birimi']}</span>
        </div>
        <div class="ai-reason">
            🤖 "{ai_reason}"
        </div>
    </div>
    """
    st.markdown(card_html, unsafe_allow_html=True)
    
    # Katman 3: Explainability Drawer (Expander)
    with st.expander("🔍 Neden bu puanı aldı? (Detaylı Analiz)"):
        c1, c2 = st.columns([1, 1])
        with c1:
            st.write(f"**Marka:** {row['brand']}")
            st.write(f"**Kategori:** {row['category']}")
            st.write(f"**Hız (Velocity):** %{row['hourly_velocity']*100:.2f} / saat")
        with c2:
            st.write("**Risk Bayrakları:**")
            flags = row.get('risk_flags', '[]')
            if flags == '[]' or not flags:
                st.success("Temiz (Risk Yok)")
            else:
                st.warning(f"{flags}")
        
        # Geri Bildirim Butonları
        fb_col1, fb_col2, _ = st.columns([1, 1, 4])
        with fb_col1:
            if st.button("👍 Doğru", key=f"up_{row['ilan_id']}"):
                st.toast("Geri bildirim alındı: Model doğrulandı.")
        with fb_col2:
            if st.button("👎 Hatalı", key=f"down_{row['ilan_id']}"):
                st.toast("Geri bildirim alındı: Threshold ayarlanacak.")

def render_analyst_mode(df):
    """Katman 4: Analist Modu (Detaylı Veriler)"""
    st.markdown("---")
    st.subheader("🧪 Analist Laboratuvarı")
    
    tab1, tab2 = st.tabs(["📊 Dağılım", "📄 Ham Veri"])
    
    with tab1:
        # Fiyat vs Skor Dağılımı
        fig = px.scatter(
            df, 
            x="fiyat_norm", 
            y="opportunity_score", 
            color="decision_label",
            hover_data=["baslik", "brand"],
            title="Fiyat / Skor Dağılımı",
            color_discrete_map={
                "💎 HIDDEN GEM": "#00b4d8",
                "✅ GOOD DEAL": "#2a9d8f",
                "🎲 SPECULATIVE": "#e9c46a",
                "NEUTRAL": "#888888"
            }
        )
        st.plotly_chart(fig, use_container_width=True)
        
    with tab2:
        st.dataframe(df)

# --- ANA UYGULAMA AKIŞI ---
def main():
    # Sidebar: Filtreler ve Modlar
    st.sidebar.title("🧠 Cognitive Radar")
    
    # Veri Yükleme
    df = load_data()
    if df.empty:
        st.sidebar.warning("Veritabanı boş veya bulunamadı. Mock veri gösteriliyor.")
        df = generate_mock_data()

    # Sidebar Filtreleri
    categories = ["Tümü"] + list(df['category'].unique())
    selected_cat = st.sidebar.selectbox("Kategori", categories)
    
    brands = ["Tümü"] + list(df['brand'].unique())
    selected_brand = st.sidebar.selectbox("Marka", brands)
    
    analyst_mode = st.sidebar.toggle("Analist Modu", value=False)
    
    # Filtreleme Mantığı
    filtered_df = df.copy()
    if selected_cat != "Tümü":
        filtered_df = filtered_df[filtered_df['category'] == selected_cat]
    if selected_brand != "Tümü":
        filtered_df = filtered_df[filtered_df['brand'] == selected_brand]

    # --- KATMAN 1: PULSE (Nabız) ---
    st.title("Piyasa Bakışı")
    render_pulse_metrics(filtered_df)
    st.markdown("---")

    # --- KATMAN 2: CURATED FEED (Seçilmiş Fırsatlar) ---
    st.subheader("🎯 Sizin İçin Seçilenler")
    
    # Sadece aksiyon alınabilir ilanları göster (Neutral'ı gizle)
    actionable_df = filtered_df[filtered_df['decision_label'].isin(["💎 HIDDEN GEM", "✅ GOOD DEAL", "🎲 SPECULATIVE"])]
    
    if actionable_df.empty:
        st.info("😴 Şu an piyasa sakin. Bakmaya değer bir anomali yok.")
    else:
        # İlanları Skor'a göre sırala (En yüksek en üstte)
        actionable_df = actionable_df.sort_values(by="opportunity_score", ascending=False)
        
        # Kartları 3 kolonlu ızgarada göster (Responsive)
        cols = st.columns(3)
        for idx, (_, row) in enumerate(actionable_df.iterrows()):
            with cols[idx % 3]:
                render_opportunity_card(row)

    # --- KATMAN 4: ANALİST MODU (Opsiyonel) ---
    if analyst_mode:
        render_analyst_mode(filtered_df)

if __name__ == "__main__":
    main()