from odoo import models, fields, api

class ResPartner(models.Model):
    _inherit = 'res.partner'
    
    orange_money_msisdn = fields.Char(
        string='Numéro Orange Money',
        help="Numéro de téléphone Orange Money du client"
    )
    
    orange_money_transaction_ids = fields.One2many(
        'orange.money.transaction',
        'partner_id',
        string='Transactions Orange Money'
    )
    
    orange_money_transaction_count = fields.Integer(
        string='Nombre de transactions Orange Money',
        compute='_compute_orange_money_stats'
    )
    
    orange_money_total_amount = fields.Float(
        string='Montant total Orange Money',
        compute='_compute_orange_money_stats'
    )
    
    orange_money_success_rate = fields.Float(
        string='Taux de réussite Orange Money (%)',
        compute='_compute_orange_money_stats'
    )

    # @api.depends('orange_money_transaction_ids.status', 'orange_money_transaction_ids.amount')
    # def _compute_orange_money_stats(self):
    #     for partner in self:
    #         transactions = partner.orange_money_transaction_ids
    #         partner.orange_money_transaction_count = len(transactions)
            
    #         successful_transactions = transactions.filtered(lambda t: t.status == 'SUCCESS')
    #         partner.orange_money_total_amount = sum(successful_transactions.mapped('amount'))
            
    #         if transactions:
    #             partner.orange_money_success_rate = (len(successful_transactions) / len(transactions)) * 100
    #         else:
    #             partner.orange_money_success_rate = 0.0

    # def action_view_orange_money_transactions(self):
    #     """Action pour voir les transactions Orange Money de ce client"""
    #     return {
    #         'name': f'Transactions Orange Money - {self.name}',
    #         'type': 'ir.actions.act_window',
    #         'view_mode': 'tree,form',
    #         'res_model': 'orange.money.transaction',
    #         'domain': [('partner_id', '=', self.id)],
    #         'context': {
    #             'default_partner_id': self.id,
    #             'default_customer_msisdn': self.orange_money_msisdn,
    #         },
    #     }

    # @api.constrains('orange_money_msisdn')
    # def _check_orange_money_msisdn(self):
    #     """Valider le format du numéro Orange Money"""
    #     for partner in self:
    #         if partner.orange_money_msisdn:
    #             # Supprimer les espaces et caractères spéciaux
    #             msisdn = ''.join(filter(str.isdigit, partner.orange_money_msisdn))
                
    #             # Vérifier le format sénégalais
    #             if not (msisdn.startswith('221') and len(msisdn) == 12) and not (len(msisdn) == 9):
    #                 from odoo.exceptions import ValidationError
    #                 raise ValidationError(
    #                     "Le numéro Orange Money doit être au format sénégalais (ex: 771234567 ou 221771234567)"
    #                 )
    
   