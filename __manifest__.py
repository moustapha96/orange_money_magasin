{
    'name': 'OM-MAGASIN',
    'version': '1.0',
    'summary': 'Intégration Orange Money pour les paiements',
    'description': """
        Module d'intégration Orange Money pour Odoo
        ==========================================
        Fonctionnalités :
        * Configuration OAuth2 simple
        * Génération de QR codes pour paiements
        * Suivi des transactions
        * Génération automatique de factures PDF
        * Intégration avec les commandes de vente
    """,
    'category': 'Immobilier',
    'depends': [
        'base',
        'sale',
        'account',
        'mail',
    ],
    'installable': True,
    'auto_install': False,
    'application': True,
    'external_dependencies': {
        'python': ['requests'],
    },
    'images': ['static/description/icon.png'],
    'data': [
        'security/ir.model.access.csv',
        'views/menus.xml',
        'views/orange_money_config_views.xml',
        'views/orange_money_transaction_views.xml',
        
        # 'views/sale_order_views.xml',
        'views/orange_money_menus.xml',
        # 'views/res_partner_views.xml',
    ],
    
    'license': 'LGPL-3',
}
