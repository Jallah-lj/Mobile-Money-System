def get_custom_css():
    return """
    <style>
        /* Import Google Font */
        @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&display=swap');
        /* FontAwesome CDN */
        @import url('https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css');

        html, body, [class*="css"] {
            font-family: 'Roboto', sans-serif;
            background-color: #f2f4f8;
        }

        /* Opay-like Green Theme */
        :root {
            --primary-color: #00C853; /* Vibrant Green */
            --secondary-color: #1B5E20; /* Darker Green */
            --bg-color: #f2f4f8;
            --text-color: #333;
            --accent-color: #ffffff;
        }

        /* Hides Streamlit Default Elements */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        
        /* Main Container */
        .block-container {
            padding-top: 1rem !important;
            padding-bottom: 2rem !important;
        }

        /* Animations */
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        @keyframes pulse {
            0% { transform: scale(1); }
            50% { transform: scale(1.02); }
            100% { transform: scale(1); }
        }

        /* Card Styles */
        .stContainer, .css-1r6slb0, .css-12oz5g7 {
            animation: fadeIn 0.5s ease-out;
        }

        /* Wallet Card - Opay Style */
        .wallet-card {
            background: linear-gradient(135deg, #00C853 0%, #009624 100%);
            color: white;
            padding: 25px;
            border-radius: 20px;
            box-shadow: 0 10px 25px rgba(0, 200, 83, 0.3);
            margin-bottom: 20px;
            position: relative;
            overflow: hidden;
            animation: fadeIn 0.8s ease-out;
        }
        
        .wallet-card::before {
            content: "";
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: radial-gradient(circle, rgba(255,255,255,0.1) 0%, transparent 60%);
            transform: rotate(30deg);
        }

        .balance-label {
            font-size: 0.9rem;
            opacity: 0.9;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .balance-value {
            font-size: 2.5rem;
            font-weight: 700;
            margin: 10px 0;
            text-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }

        .wallet-details {
            display: flex;
            justify-content: space-between;
            font-size: 0.9rem;
        }

        /* Custom Button Styling */
        .stButton > button {
            background-color: white !important;
            color: #00C853 !important;
            border: 2px solid #00C853 !important;
            border-radius: 12px !important;
            padding: 0.5rem 1rem !important;
            font-weight: 600 !important;
            transition: all 0.3s ease !important;
            width: 100%;
        }

        .stButton > button:hover {
            background-color: #00C853 !important;
            color: white !important;
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0, 200, 83, 0.2);
        }
        
        /* Primary Action Buttons */
        div[data-testid="stForm"] .stButton > button {
             background-color: #00C853 !important;
             color: white !important;
             border: none !important;
        }

        /* Grid Icons for Actions */
        .action-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            padding: 10px;
            background: white;
            border-radius: 15px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.02);
            margin-bottom: 20px;
        }

        .action-item {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 10px;
            cursor: pointer;
            transition: transform 0.2s;
        }

        .action-item:hover {
            transform: scale(1.1);
        }

        .icon-circle {
            width: 50px;
            height: 50px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 8px;
            font-size: 1.2rem;
            color: white;
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        }

        .bg-green { background: #00C853; }
        .bg-blue { background: #2979FF; }
        .bg-orange { background: #FF9100; }
        .bg-red { background: #FF3D00; }
        .bg-purple { background: #651FFF; }

        .action-label {
            font-size: 0.8rem;
            color: #555;
            font-weight: 500;
            text-align: center;
        }
        
        /* Transaction List */
        .tx-card {
            background: white;
            padding: 15px;
            border-radius: 12px;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            transition: background 0.2s;
            border-left: 4px solid transparent;
        }
        
        .tx-card:hover {
            background: #fcfcfc;
        }

        .tx-icon {
            width: 40px;
            height: 40px;
            border-radius: 50%;
            background: #f0f2f5;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-right: 15px;
            font-size: 1.1rem;
        }

        .tx-details {
            flex-grow: 1;
        }
        
        .tx-amount.credit { color: #00C853; font-weight: bold; }
        .tx-amount.debit { color: #d32f2f; font-weight: bold; }

        /* Styling Streamlit Forms (Auth Forms) */
        [data-testid="stForm"] {
            background-color: white;
            padding: 2rem;
            border-radius: 15px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.05);
            border: 1px solid #eee;
        }

        /* Input fields better styling */
        .stTextInput > div > div > input {
            border-radius: 10px;
            border: 1px solid #ddd;
            padding-left: 10px;
        }

    </style>
    """
